import hmac
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, select, text

from backend.app.core.config import Settings
from backend.app.db.models.job import Job, JobStatus


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready"]


class JobDurationMetrics(BaseModel):
    count: int = Field(ge=0)
    total_seconds: float = Field(ge=0)
    average_seconds: float = Field(ge=0)
    maximum_seconds: float = Field(ge=0)


class JobMetricsResponse(BaseModel):
    queue_length: int = Field(ge=0)
    running: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    processing_duration: JobDurationMetrics


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


def _check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_data_directory(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".readiness-", dir=data_dir) as probe:
        probe.write(b"ready")
        probe.flush()


def _readiness_failure(request: Request, component: str, exc: Exception) -> None:
    request_id = getattr(request.state, "request_id", "-")
    logger.bind(request_id=request_id).error(
        "Readiness check failed component={} exception_type={}",
        component,
        type(exc).__name__,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(request: Request) -> ReadinessResponse:
    settings: Settings = request.app.state.settings
    engine: Engine = request.app.state.db_engine

    try:
        _check_database(engine)
    except Exception as exc:
        _readiness_failure(request, "database", exc)
        raise HTTPException(status_code=503, detail="Service not ready") from None

    try:
        _check_data_directory(settings.data_dir)
    except Exception as exc:
        _readiness_failure(request, "data_directory", exc)
        raise HTTPException(status_code=503, detail="Service not ready") from None

    return ReadinessResponse(status="ready")


def _require_metrics_token(request: Request) -> None:
    configured = request.app.state.settings.metrics_token
    if configured is None:
        raise HTTPException(status_code=404, detail="Not Found")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    expected = configured.get_secret_value()
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=401,
            detail="Metrics authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _duration_metrics(rows: list[tuple[datetime, datetime]]) -> JobDurationMetrics:
    durations = [max(0.0, (finished - started).total_seconds()) for started, finished in rows]
    total = sum(durations)
    return JobDurationMetrics(
        count=len(durations),
        total_seconds=round(total, 6),
        average_seconds=round(total / len(durations), 6) if durations else 0.0,
        maximum_seconds=round(max(durations), 6) if durations else 0.0,
    )


@router.get("/metrics", response_model=JobMetricsResponse)
async def job_metrics(request: Request) -> JobMetricsResponse:
    _require_metrics_token(request)
    with request.app.state.session_factory() as session:
        counts = {
            status: count
            for status, count in session.execute(
                select(Job.status, func.count()).group_by(Job.status)
            )
        }
        duration_rows = list(
            session.execute(
                select(Job.started_at, Job.finished_at).where(
                    Job.status.in_(
                        [
                            JobStatus.SUCCEEDED,
                            JobStatus.FAILED,
                            JobStatus.CANCELLED,
                        ]
                    ),
                    Job.started_at.is_not(None),
                    Job.finished_at.is_not(None),
                )
            )
        )
    return JobMetricsResponse(
        queue_length=counts.get(JobStatus.QUEUED, 0),
        running=counts.get(JobStatus.RUNNING, 0),
        succeeded=counts.get(JobStatus.SUCCEEDED, 0),
        failed=counts.get(JobStatus.FAILED, 0),
        cancelled=counts.get(JobStatus.CANCELLED, 0),
        processing_duration=_duration_metrics(duration_rows),
    )
