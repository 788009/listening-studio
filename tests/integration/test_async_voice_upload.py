from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.services.job_storage import JobStorage
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voice_uploads import (
    VOICE_UPLOAD_JOB_TYPE,
    VoiceUploadService,
)
from backend.app.workers.jobs import JobWorker
from backend.app.workers.voice_upload import VoiceUploadJobHandler


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AsyncVoiceUploadIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'async-voice.sqlite3'}"
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
            max_upload_bytes=1024 * 1024,
        )
        self.app = create_app(self.settings)
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.job_storage = JobStorage(self.settings.data_dir)
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(),
            json={"userId": "TeacherOne", "username": "Teacher"},
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers() -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: "teacher",
        }

    @staticmethod
    def wav_bytes(duration_seconds: float = 2.0) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * int(duration_seconds * 8000))
        return output.getvalue()

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

    def upload(self, content: bytes | None = None) -> httpx.Response:
        return self.send(
            "POST",
            "/api/voices",
            headers=self.headers(),
            data={"title": "Async voice", "visibility": "public"},
            files={
                "file": (
                    "reference.wav",
                    content if content is not None else self.wav_bytes(),
                    "audio/wav",
                )
            },
        )

    def worker(self, fake: FakeCosyVoiceIntegration) -> JobWorker:
        service = VoiceUploadService(
            storage=self.voice_storage,
            max_upload_bytes=self.settings.max_upload_bytes,
            integration=fake,
            job_storage=self.job_storage,
        )
        return JobWorker(
            self.app.state.session_factory,
            {VOICE_UPLOAD_JOB_TYPE: VoiceUploadJobHandler(service)},
            poll_interval_seconds=0.01,
        )

    def test_api_returns_before_model_and_worker_is_idempotent(self) -> None:
        fake = FakeCosyVoiceIntegration()
        response = self.upload()

        self.assertEqual(response.status_code, 202)
        voice_id = response.json()["voiceId"]
        job_id = response.json()["jobId"]
        self.assertEqual(fake.calls, [])
        self.assertTrue(self.job_storage.reference_path(job_id).is_file())
        with self.app.state.session_factory() as session:
            voice = session.get(Voice, voice_id)
            job = session.get(Job, job_id)
            assert voice and job
            self.assertEqual(voice.status, VoiceStatus.PENDING)
            self.assertEqual(voice.visibility, VoiceVisibility.PRIVATE)
            self.assertEqual(job.status, JobStatus.QUEUED)

        worker = self.worker(fake)
        self.assertTrue(worker.run_once())
        with self.app.state.session_factory() as session:
            voice = session.get(Voice, voice_id)
            job = session.get(Job, job_id)
            assert voice and job
            self.assertEqual(voice.status, VoiceStatus.READY)
            self.assertEqual(voice.visibility, VoiceVisibility.PUBLIC)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(job.progress, 100)
            self.assertEqual(job.result_type, "voice")
            self.assertEqual(job.result_id, voice_id)
            job.status = JobStatus.QUEUED
            job.progress = 0
            job.result_type = None
            job.result_id = None
            job.finished_at = None
            session.commit()

        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(self.job_storage.directory(job_id).exists())
        self.assertTrue(self.voice_storage.exists(voice_id, VoiceAsset.MODEL))
        self.assertTrue(worker.run_once())
        self.assertEqual(len(fake.calls), 1)
        with self.app.state.session_factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(job.attempt_count, 2)

    def test_worker_failure_marks_voice_and_job_and_cleans_staging(self) -> None:
        response = self.upload()
        self.assertEqual(response.status_code, 202)
        voice_id = response.json()["voiceId"]
        job_id = response.json()["jobId"]
        fake = FakeCosyVoiceIntegration(failure=RuntimeError("model failed"))

        self.assertTrue(self.worker(fake).run_once())

        with self.app.state.session_factory() as session:
            voice = session.get(Voice, voice_id)
            job = session.get(Job, job_id)
            assert voice and job
            self.assertEqual(voice.status, VoiceStatus.FAILED)
            self.assertEqual(voice.visibility, VoiceVisibility.PRIVATE)
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertIn("Verify the reference WAV", job.error_summary or "")
        self.assertFalse(self.voice_storage.directory(voice_id).exists())
        self.assertFalse(self.job_storage.directory(job_id).exists())

    def test_invalid_upload_creates_no_voice_or_job(self) -> None:
        response = self.upload(b"not a wav")
        self.assertEqual(response.status_code, 422)
        with self.app.state.session_factory() as session:
            voice_count = session.scalar(select(func.count()).select_from(Voice))
            job_count = session.scalar(select(func.count()).select_from(Job))
        self.assertEqual(voice_count, 0)
        self.assertEqual(job_count, 0)
        self.assertFalse(self.job_storage.root.exists())


if __name__ == "__main__":
    unittest.main()
