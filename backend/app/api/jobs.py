from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from loguru import logger
from sqlalchemy.orm import Session

from backend.app.api.job_schemas import (
    JobListResponse,
    JobResponse,
    JobResultResponse,
)
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import require_completed_profile
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.jobs import JobService, MAX_JOB_TYPE_LENGTH


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _response(job: Job) -> JobResponse:
    result = None
    if job.result_type is not None and job.result_id is not None:
        result = JobResultResponse(type=job.result_type, id=job.result_id)
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        input_summary=job.input_summary,
        result=result,
        error_summary=job.error_summary,
        cancel_requested=job.cancel_requested,
        retryable=job.retryable,
        attempt_count=job.attempt_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("", response_model=JobListResponse, response_model_exclude_none=True)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    job_status: JobStatus | None = Query(default=None, alias="status"),
    job_type: str | None = Query(
        default=None,
        alias="type",
        min_length=1,
        max_length=MAX_JOB_TYPE_LENGTH,
    ),
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> JobListResponse:
    result = JobService().list_owned_jobs(
        session,
        current_user,
        page=page,
        page_size=page_size,
        status=job_status,
        job_type=job_type,
    )
    return JobListResponse(
        items=[_response(job) for job in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    response_model_exclude_none=True,
)
async def get_job(
    job_id: ResourceId,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    return _response(JobService().get_owned_job(session, current_user, job_id))


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
    response_model_exclude_none=True,
)
async def cancel_job(
    job_id: ResourceId,
    request: Request,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = JobService().request_cancel(session, current_user, job_id)
    logger.bind(
        request_id=request.state.request_id,
        job_id=job.id,
        user_db_id=current_user.id,
        resource_type="job",
        resource_id=job.id,
    ).info(
        "Job cancellation requested job_id={} status={}",
        job.id,
        job.status.value,
    )
    return _response(job)
