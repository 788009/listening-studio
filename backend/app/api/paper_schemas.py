from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.app.api.schemas import ResourceId, Title
from backend.app.api.tag_schemas import TagApiModel
from backend.app.db.models.paper import PaperStatus


class PaperPresetParametersRequest(TagApiModel):
    intro_silence_milliseconds: int = Field(ge=0, le=60_000)
    inter_item_silence_milliseconds: int = Field(ge=0, le=60_000)
    repeat_count: int = Field(ge=1, le=10)
    outro_silence_milliseconds: int = Field(ge=0, le=60_000)


class PaperPresetWriteRequest(PaperPresetParametersRequest):
    name: str = Field(min_length=1, max_length=200)


class PaperPresetResponse(TagApiModel):
    id: int
    name: str
    is_builtin: bool
    intro_silence_milliseconds: int
    inter_item_silence_milliseconds: int
    repeat_count: int
    outro_silence_milliseconds: int


class PaperCreateRequest(TagApiModel):
    title: Title
    preset_id: ResourceId
    audio_ids: list[ResourceId] = Field(min_length=1, max_length=100)


class PaperItemResponse(TagApiModel):
    id: int
    audio_id: int
    title: str
    position: int = Field(ge=0)


class PaperResponse(TagApiModel):
    id: int
    title: str
    status: PaperStatus
    preset_id: int | None
    preset_name: str | None
    intro_silence_milliseconds: int
    inter_item_silence_milliseconds: int
    repeat_count: int
    outro_silence_milliseconds: int
    result_audio_id: int | None = None
    error_summary: str | None = None
    items: list[PaperItemResponse]
    created_at: datetime
    updated_at: datetime


class PaperListResponse(TagApiModel):
    items: list[PaperResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
