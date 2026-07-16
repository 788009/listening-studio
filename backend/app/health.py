import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import Engine, text

from backend.app.core.config import Settings


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready"]


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
