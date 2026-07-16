from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from backend.app.api.tag_schemas import TagApiModel
from backend.app.db.models.job import JobStatus


class JobResultResponse(TagApiModel):
    type: str
    id: int


class JobResponse(TagApiModel):
    id: int
    type: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    input_summary: dict[str, Any]
    result: JobResultResponse | None = None
    error_summary: str | None = None
    cancel_requested: bool
    retryable: bool
    attempt_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobListResponse(TagApiModel):
    items: list[JobResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
