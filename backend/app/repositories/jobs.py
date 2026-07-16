from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User


class JobRepository:
    def create(
        self,
        session: Session,
        *,
        job_type: str,
        owner: User,
        input_summary: dict[str, Any],
        retryable: bool,
    ) -> Job:
        job = Job(
            type=job_type,
            owner=owner,
            input_summary=input_summary,
            retryable=retryable,
        )
        session.add(job)
        session.flush()
        return job

    def get_by_id(self, session: Session, job_id: int) -> Job | None:
        return session.get(Job, job_id)

    def list_for_owner(
        self,
        session: Session,
        *,
        owner_id: int,
        page: int,
        page_size: int,
        status: JobStatus | None = None,
        job_type: str | None = None,
    ) -> tuple[list[Job], int]:
        filters = [Job.owner_id == owner_id]
        if status is not None:
            filters.append(Job.status == status)
        if job_type is not None:
            filters.append(Job.type == job_type)
        total = session.scalar(select(func.count()).select_from(Job).where(*filters))
        statement = (
            select(Job)
            .options(selectinload(Job.owner))
            .where(*filters)
            .order_by(Job.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(session.scalars(statement)), int(total or 0)

    def claim_next(self, session: Session) -> Job | None:
        candidate_id = session.scalar(
            select(Job.id)
            .where(
                Job.status == JobStatus.QUEUED,
                Job.cancel_requested.is_(False),
            )
            .order_by(Job.id)
            .limit(1)
        )
        if candidate_id is None:
            return None
        now = self._now()
        result = session.execute(
            update(Job)
            .where(
                Job.id == candidate_id,
                Job.status == JobStatus.QUEUED,
                Job.cancel_requested.is_(False),
            )
            .values(
                status=JobStatus.RUNNING,
                claimed_at=now,
                started_at=now,
                finished_at=None,
                error_summary=None,
                attempt_count=Job.attempt_count + 1,
            )
        )
        if result.rowcount != 1:
            session.expire_all()
            return None
        session.flush()
        return session.get(Job, candidate_id)

    def update_progress(self, session: Session, job_id: int, progress: int) -> bool:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.cancel_requested.is_(False),
                Job.progress <= progress,
            )
            .values(progress=progress)
        )
        return result.rowcount == 1

    def complete(
        self,
        session: Session,
        job_id: int,
        *,
        result_type: str | None,
        result_id: int | None,
    ) -> bool:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.RUNNING,
                Job.cancel_requested.is_(False),
            )
            .values(
                status=JobStatus.SUCCEEDED,
                progress=100,
                result_type=result_type,
                result_id=result_id,
                finished_at=self._now(),
                error_summary=None,
            )
        )
        return result.rowcount == 1

    def fail(self, session: Session, job_id: int, error_summary: str) -> bool:
        result = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING)
            .values(
                status=JobStatus.FAILED,
                error_summary=error_summary,
                finished_at=self._now(),
            )
        )
        return result.rowcount == 1

    def mark_cancelled(self, session: Session, job_id: int) -> bool:
        result = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
            .values(
                status=JobStatus.CANCELLED,
                cancel_requested=True,
                finished_at=self._now(),
            )
        )
        return result.rowcount == 1

    def is_cancel_requested(self, session: Session, job_id: int) -> bool:
        return bool(
            session.scalar(select(Job.cancel_requested).where(Job.id == job_id))
        )

    def recover_interrupted(self, session: Session) -> dict[str, int]:
        now = self._now()
        cancelled = session.execute(
            update(Job)
            .where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                Job.cancel_requested.is_(True),
            )
            .values(status=JobStatus.CANCELLED, finished_at=now)
        ).rowcount
        retried = session.execute(
            update(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.cancel_requested.is_(False),
                Job.retryable.is_(True),
            )
            .values(
                status=JobStatus.QUEUED,
                progress=0,
                claimed_at=None,
                started_at=None,
                error_summary=None,
            )
        ).rowcount
        failed = session.execute(
            update(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.cancel_requested.is_(False),
                Job.retryable.is_(False),
            )
            .values(
                status=JobStatus.FAILED,
                error_summary="Worker stopped before the task completed",
                finished_at=now,
            )
        ).rowcount
        session.execute(
            update(Job)
            .where(
                Job.status == JobStatus.QUEUED,
                Job.cancel_requested.is_(False),
            )
            .values(claimed_at=None, started_at=None, finished_at=None)
        )
        return {
            "cancelled": cancelled,
            "retried": retried,
            "failed": failed,
        }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
