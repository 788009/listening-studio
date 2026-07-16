from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User
from backend.app.repositories.jobs import JobRepository


MAX_JOB_INPUT_SUMMARY_BYTES = 4096
MAX_JOB_TYPE_LENGTH = 64
_JOB_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class JobListResult:
    items: list[Job]
    total: int


class JobService:
    def __init__(self, repository: JobRepository | None = None) -> None:
        self.repository = repository or JobRepository()

    def create_job(
        self,
        session: Session,
        *,
        owner: User,
        job_type: str,
        input_summary: dict[str, Any],
        retryable: bool = False,
    ) -> Job:
        normalized_type = self.normalize_job_type(job_type)
        summary = self._validate_input_summary(input_summary)
        if not owner.is_profile_complete:
            raise DomainValidationError("Job owner profile is incomplete")
        return self.repository.create(
            session,
            job_type=normalized_type,
            owner=owner,
            input_summary=summary,
            retryable=retryable,
        )

    def get_owned_job(self, session: Session, owner: User, job_id: int) -> Job:
        job = self.repository.get_by_id(session, job_id)
        if job is None or job.owner_id != owner.id:
            raise NotFoundError("Job not found")
        return job

    def list_owned_jobs(
        self,
        session: Session,
        owner: User,
        *,
        page: int,
        page_size: int,
        status: JobStatus | None = None,
        job_type: str | None = None,
    ) -> JobListResult:
        normalized_type = self.normalize_job_type(job_type) if job_type else None
        items, total = self.repository.list_for_owner(
            session,
            owner_id=owner.id,
            page=page,
            page_size=page_size,
            status=status,
            job_type=normalized_type,
        )
        return JobListResult(items, total)

    def request_cancel(self, session: Session, owner: User, job_id: int) -> Job:
        job = self.get_owned_job(session, owner, job_id)
        if job.status is JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            job.cancel_requested = True
            job.finished_at = datetime.now(timezone.utc)
        elif job.status is JobStatus.RUNNING:
            job.cancel_requested = True
        elif job.status not in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            raise ConflictError("Job cannot be cancelled")
        session.flush()
        return job

    @staticmethod
    def normalize_job_type(value: str) -> str:
        if not isinstance(value, str):
            raise DomainValidationError(
                "Job type is invalid",
                details={"field": "type"},
            )
        normalized = value.strip().casefold()
        if (
            not normalized
            or len(normalized) > MAX_JOB_TYPE_LENGTH
            or _JOB_TYPE_PATTERN.fullmatch(normalized) is None
        ):
            raise DomainValidationError(
                "Job type must use lowercase ASCII letters, numbers, and underscores",
                details={"field": "type"},
            )
        return normalized

    @staticmethod
    def _validate_input_summary(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise DomainValidationError(
                "Job input summary must be an object",
                details={"field": "inputSummary"},
            )
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise DomainValidationError(
                "Job input summary must be JSON serializable",
                details={"field": "inputSummary"},
            ) from exc
        if len(encoded.encode("utf-8")) > MAX_JOB_INPUT_SUMMARY_BYTES:
            raise DomainValidationError(
                "Job input summary is too large",
                details={
                    "field": "inputSummary",
                    "maxBytes": MAX_JOB_INPUT_SUMMARY_BYTES,
                },
            )
        return json.loads(encoded)
