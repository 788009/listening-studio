from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from threading import Event, Lock, Thread

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.jobs import JobRepository
from backend.app.repositories.users import UserRepository
from backend.app.services.job_storage import JobStorage
from backend.app.services.jobs import JobService
from backend.app.workers.jobs import JobContext, JobPayload, JobResult, JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class JobIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'jobs.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )
        self.app = create_app(self.settings)
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers(subject: str) -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: subject,
        }

    @staticmethod
    async def request(
        app: FastAPI,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def complete_profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def user(session: Session, user_id: str) -> User:
        user = UserRepository().get_by_user_id(session, user_id)
        assert user is not None
        return user

    def create_job(
        self,
        session: Session,
        *,
        owner_id: str = "TeacherOne",
        job_type: str = "fake_generation",
        retryable: bool = False,
    ) -> Job:
        return JobService().create_job(
            session,
            owner=self.user(session, owner_id),
            job_type=job_type,
            input_summary={"title": "Summary only"},
            retryable=retryable,
        )

    def test_worker_runs_in_order_and_persists_progress_once(self) -> None:
        with self.app.state.session_factory() as session:
            first = self.create_job(session)
            second = self.create_job(session)
            session.commit()
            job_ids = [first.id, second.id]

        handled: list[int] = []

        def handler(context: JobContext, job: JobPayload) -> JobResult:
            handled.append(job.id)
            context.update_progress(25)
            context.update_progress(75)
            return JobResult("audio", job.id)

        worker = JobWorker(
            self.app.state.session_factory,
            {"fake_generation": handler},
            poll_interval_seconds=0.01,
        )
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        self.assertEqual(handled, job_ids)

        with self.app.state.session_factory() as session:
            jobs = [session.get(Job, job_id) for job_id in job_ids]
            self.assertTrue(all(job is not None for job in jobs))
            self.assertEqual([job.status for job in jobs if job], [
                JobStatus.SUCCEEDED,
                JobStatus.SUCCEEDED,
            ])
            self.assertEqual([job.progress for job in jobs if job], [100, 100])
            self.assertEqual([job.attempt_count for job in jobs if job], [1, 1])
            self.assertEqual(handled.count(first.id), 1)

    def test_worker_runs_jobs_concurrently_and_waits_during_shutdown(self) -> None:
        with self.app.state.session_factory() as session:
            jobs = [self.create_job(session) for _ in range(3)]
            session.commit()
            job_ids = [job.id for job in jobs]

        release_handlers = Event()
        both_started = Event()
        state_lock = Lock()
        active_count = 0
        maximum_active_count = 0

        def handler(context: JobContext, job: JobPayload) -> JobResult:
            del context
            nonlocal active_count, maximum_active_count
            with state_lock:
                active_count += 1
                maximum_active_count = max(maximum_active_count, active_count)
                if active_count == 2:
                    both_started.set()
            self.assertTrue(release_handlers.wait(3))
            with state_lock:
                active_count -= 1
            return JobResult("audio", job.id)

        stop_event = Event()
        worker = JobWorker(
            self.app.state.session_factory,
            {"fake_generation": handler},
            poll_interval_seconds=0.01,
            max_concurrency=2,
        )
        worker_thread = Thread(target=worker.run_forever, args=(stop_event,))
        worker_thread.start()
        try:
            self.assertTrue(both_started.wait(3))
            stop_event.set()
            worker_thread.join(0.05)
            self.assertTrue(worker_thread.is_alive())
            release_handlers.set()
            worker_thread.join(3)
        finally:
            release_handlers.set()
            stop_event.set()
            worker_thread.join(3)

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(maximum_active_count, 2)
        with self.app.state.session_factory() as session:
            completed = [session.get(Job, job_id) for job_id in job_ids]
            self.assertTrue(all(job is not None for job in completed))
            self.assertEqual(
                [job.status for job in completed if job],
                [
                    JobStatus.SUCCEEDED,
                    JobStatus.SUCCEEDED,
                    JobStatus.QUEUED,
                ],
            )

    def test_worker_rejects_invalid_concurrency(self) -> None:
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                JobWorker(
                    self.app.state.session_factory,
                    {},
                    max_concurrency=value,
                )

    def test_handler_failure_and_cancellation_reach_terminal_states(self) -> None:
        with self.app.state.session_factory() as session:
            failed = self.create_job(session, job_type="failing")
            running_cancel = self.create_job(session, job_type="cancelling")
            queued_cancel = self.create_job(session, job_type="queued_cancel")
            owner = self.user(session, "TeacherOne")
            JobService().request_cancel(session, owner, queued_cancel.id)
            session.commit()

        def fail(context: JobContext, job: JobPayload) -> None:
            del context, job
            raise RuntimeError("sensitive handler message")

        def cancel(context: JobContext, job: JobPayload) -> None:
            with self.app.state.session_factory() as session:
                owner = self.user(session, "TeacherOne")
                JobService().request_cancel(session, owner, job.id)
                session.commit()
            context.raise_if_cancel_requested()

        worker = JobWorker(
            self.app.state.session_factory,
            {"failing": fail, "cancelling": cancel},
            poll_interval_seconds=0.01,
        )
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())

        with self.app.state.session_factory() as session:
            failed_job = session.get(Job, failed.id)
            cancelled_job = session.get(Job, running_cancel.id)
            queued_job = session.get(Job, queued_cancel.id)
            assert failed_job and cancelled_job and queued_job
            self.assertEqual(failed_job.status, JobStatus.FAILED)
            self.assertEqual(failed_job.error_summary, "Handler failed: RuntimeError")
            self.assertNotIn("sensitive", failed_job.error_summary)
            self.assertEqual(cancelled_job.status, JobStatus.CANCELLED)
            self.assertEqual(queued_job.status, JobStatus.CANCELLED)

    def test_restart_recovery_retries_only_safe_jobs(self) -> None:
        repository = JobRepository()
        with self.app.state.session_factory() as session:
            retryable = self.create_job(session, retryable=True)
            unsafe = self.create_job(session, retryable=False)
            queued = self.create_job(session, retryable=True)
            session.commit()
        with self.app.state.session_factory() as session:
            claimed = repository.claim_next(session)
            assert claimed is not None
            self.assertEqual(claimed.id, retryable.id)
            session.commit()
        with self.app.state.session_factory() as session:
            claimed = repository.claim_next(session)
            assert claimed is not None
            self.assertEqual(claimed.id, unsafe.id)
            session.commit()

        job_storage = JobStorage(self.settings.data_dir)
        for job_id in (retryable.id, unsafe.id):
            directory = job_storage.directory(job_id)
            directory.mkdir(parents=True)
            (directory / "temporary.bin").write_bytes(b"temporary")
        unknown_directory = job_storage.root / "9999"
        unknown_directory.mkdir(parents=True)

        worker = JobWorker(
            self.app.state.session_factory,
            {},
            poll_interval_seconds=0.01,
            job_storage=job_storage,
        )
        recovered = worker.recover()
        self.assertEqual(recovered, {"cancelled": 0, "retried": 1, "failed": 1})

        with self.app.state.session_factory() as session:
            retryable_job = session.get(Job, retryable.id)
            unsafe_job = session.get(Job, unsafe.id)
            queued_job = session.get(Job, queued.id)
            assert retryable_job and unsafe_job and queued_job
            self.assertEqual(retryable_job.status, JobStatus.QUEUED)
            self.assertEqual(retryable_job.progress, 0)
            self.assertEqual(unsafe_job.status, JobStatus.FAILED)
            self.assertEqual(queued_job.status, JobStatus.QUEUED)
        self.assertTrue(job_storage.directory(retryable.id).is_dir())
        self.assertFalse(job_storage.directory(unsafe.id).exists())
        self.assertTrue(unknown_directory.is_dir())

    def test_job_api_is_owner_scoped_and_cancels_queued_work(self) -> None:
        with self.app.state.session_factory() as session:
            first = self.create_job(session)
            second = self.create_job(session, owner_id="TeacherTwo")
            session.commit()

        anonymous = self.send("GET", "/api/jobs")
        listed = self.send("GET", "/api/jobs", headers=self.headers("first"))
        hidden = self.send(
            "GET",
            f"/api/jobs/{second.id}",
            headers=self.headers("first"),
        )
        cancelled = self.send(
            "POST",
            f"/api/jobs/{first.id}/cancel",
            headers=self.headers("first"),
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(listed.json()["items"][0]["id"], first.id)
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertTrue(cancelled.json()["cancelRequested"])


if __name__ == "__main__":
    unittest.main()
