from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models.job import Job, JobStatus
from backend.app.repositories.jobs import JobRepository
from backend.app.services.consistency import interrupted_job_target
from backend.app.services.job_storage import JobStorage
from backend.app.services.jobs import JobService


class JobCancelled(RuntimeError):
    pass


class JobExecutionError(RuntimeError):
    def __init__(self, summary: str) -> None:
        value = summary.strip()
        if not value or len(value) > 1000:
            raise ValueError("Job execution error summary is invalid")
        super().__init__(value)
        self.summary = value


@dataclass(frozen=True)
class JobPayload:
    id: int
    type: str
    owner_id: int
    input_summary: dict[str, Any]
    attempt_count: int


@dataclass(frozen=True)
class JobResult:
    result_type: str | None = None
    result_id: int | None = None

    def __post_init__(self) -> None:
        if (self.result_type is None) != (self.result_id is None):
            raise ValueError("Job result type and ID must be provided together")
        if self.result_type is not None:
            object.__setattr__(
                self,
                "result_type",
                JobService.normalize_job_type(self.result_type),
            )
        if self.result_id is not None and (
            isinstance(self.result_id, bool)
            or not isinstance(self.result_id, int)
            or self.result_id < 1
        ):
            raise ValueError("Job result ID must be a positive integer")


class JobHandler(Protocol):
    def __call__(self, context: JobContext, job: JobPayload) -> JobResult | None:
        pass


class JobContext:
    def __init__(
        self,
        job_id: int,
        session_factory: sessionmaker[Session],
        repository: JobRepository,
    ) -> None:
        self.job_id = job_id
        self.session_factory = session_factory
        self.repository = repository

    def update_progress(self, progress: int) -> None:
        if (
            isinstance(progress, bool)
            or not isinstance(progress, int)
            or not 0 <= progress <= 100
        ):
            raise ValueError("Job progress must be between 0 and 100")
        with self.session_factory() as session:
            updated = self.repository.update_progress(session, self.job_id, progress)
            if updated:
                session.commit()
                return
            session.rollback()
        self.raise_if_cancel_requested()
        raise RuntimeError("Job is no longer running")

    def raise_if_cancel_requested(self) -> None:
        with self.session_factory() as session:
            job = self.repository.get_by_id(session, self.job_id)
            if job is None or job.status is JobStatus.CANCELLED:
                raise JobCancelled()
            if job.cancel_requested:
                raise JobCancelled()
            if job.status is not JobStatus.RUNNING:
                raise RuntimeError("Job is no longer running")


class JobWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: dict[str, JobHandler],
        *,
        poll_interval_seconds: float = 1.0,
        repository: JobRepository | None = None,
        job_storage: JobStorage | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be positive")
        self.session_factory = session_factory
        self.handlers = {
            JobService.normalize_job_type(job_type): handler
            for job_type, handler in handlers.items()
        }
        self.poll_interval_seconds = poll_interval_seconds
        self.repository = repository or JobRepository()
        self.job_storage = job_storage

    def recover(self) -> dict[str, int]:
        with self.session_factory() as session:
            interrupted = {
                job.id: (job.status, target, job.owner_id)
                for job in session.scalars(select(Job).order_by(Job.id))
                if (target := interrupted_job_target(job)) is not None
            }
            result = self.repository.recover_interrupted(session)
            session.commit()
        for job_id, (original, target, owner_id) in interrupted.items():
            cleanup_result = "not_required"
            if self.job_storage is not None and target in {
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                directory = self.job_storage.directory(job_id)
                existed = directory.exists() or directory.is_symlink()
                self.job_storage.cleanup(job_id)
                cleanup_result = "removed" if existed else "absent"
            logger.bind(
                job_id=job_id,
                user_db_id=owner_id,
                resource_type="job",
                resource_id=job_id,
            ).info(
                "Startup job recovery resource_id={} original_status={} "
                "target_status={} result=repaired temporary_cleanup={}",
                job_id,
                original.value,
                target.value,
                cleanup_result,
            )
        logger.info(
            "Job recovery completed retried={} failed={} cancelled={}",
            result["retried"],
            result["failed"],
            result["cancelled"],
        )
        return result

    def run_once(self) -> bool:
        with self.session_factory() as session:
            job = self.repository.claim_next(session)
            if job is None:
                session.rollback()
                return False
            payload = JobPayload(
                id=job.id,
                type=job.type,
                owner_id=job.owner_id,
                input_summary=dict(job.input_summary),
                attempt_count=job.attempt_count,
            )
            session.commit()

        handler = self.handlers.get(payload.type)
        if handler is None:
            self._fail(payload.id, "No handler is registered for this job type")
            return True

        context = JobContext(payload.id, self.session_factory, self.repository)
        resource_type, resource_id = self._resource_context(payload.input_summary)
        job_logger = logger.bind(
            request_id=f"job-{payload.id}",
            job_id=payload.id,
            user_db_id=payload.owner_id,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        job_logger.info("Job started job_id={} job_type={}", payload.id, payload.type)
        try:
            result = handler(context, payload) or JobResult()
            context.raise_if_cancel_requested()
        except JobCancelled:
            self._cancel(payload.id)
            job_logger.info("Job cancelled job_id={}", payload.id)
        except Exception as exc:
            summary = (
                exc.summary
                if isinstance(exc, JobExecutionError)
                else f"Handler failed: {type(exc).__name__}"
            )
            self._fail(payload.id, summary)
            job_logger.error(
                "Job failed job_id={} exception_type={}",
                payload.id,
                type(exc).__name__,
            )
        else:
            with self.session_factory() as session:
                completed = self.repository.complete(
                    session,
                    payload.id,
                    result_type=result.result_type,
                    result_id=result.result_id,
                )
                if completed:
                    session.commit()
                    job_logger.info("Job completed job_id={}", payload.id)
                else:
                    session.rollback()
                    self._cancel(payload.id)
                    job_logger.info("Job cancelled at completion job_id={}", payload.id)
        return True

    @staticmethod
    def _resource_context(input_summary: dict[str, Any]) -> tuple[str, object]:
        for key, resource_type in (
            ("batchId", "generation_batch"),
            ("paperId", "paper"),
            ("audioId", "audio"),
            ("voiceId", "voice"),
            ("itemId", "generation_batch_item"),
        ):
            value = input_summary.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return resource_type, value
        return "job", "-"

    def run_forever(self, stop_event: Event | None = None) -> None:
        stop_event = stop_event or Event()
        self.recover()
        logger.info("Job worker started")
        try:
            while not stop_event.is_set():
                processed = self.run_once()
                if not processed:
                    stop_event.wait(self.poll_interval_seconds)
        finally:
            logger.info("Job worker stopped")

    def _cancel(self, job_id: int) -> None:
        with self.session_factory() as session:
            self.repository.mark_cancelled(session, job_id)
            session.commit()
        if self.job_storage is not None:
            self.job_storage.cleanup(job_id)

    def _fail(self, job_id: int, error_summary: str) -> None:
        with self.session_factory() as session:
            if self.repository.is_cancel_requested(session, job_id):
                self.repository.mark_cancelled(session, job_id)
            else:
                self.repository.fail(session, job_id, error_summary[:1000])
            session.commit()
        if self.job_storage is not None:
            self.job_storage.cleanup(job_id)
