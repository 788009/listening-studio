from __future__ import annotations

from pydantic import Field, model_validator

from backend.app.api.schemas import ResourceId, Title
from backend.app.api.tag_schemas import AudioTagResponse, TagApiModel
from backend.app.db.models.audio import (
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)


class AudioAuthorResponse(TagApiModel):
    user_id: str
    username: str | None


class AudioUtteranceResponse(TagApiModel):
    voice_id: int
    speaker_display_name: str
    text: str
    position: int


class AudioResponse(TagApiModel):
    id: int
    author: AudioAuthorResponse
    title: str
    text: str
    source_type: AudioSourceType
    status: AudioStatus
    visibility: AudioVisibility
    duration_seconds: float | None
    sample_rate: int | None
    error_summary: str | None = None
    tags: list[AudioTagResponse]
    utterances: list[AudioUtteranceResponse]


class AudioListResponse(TagApiModel):
    items: list[AudioResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class AudioUpdateRequest(TagApiModel):
    title: Title | None = None
    tag_ids: list[ResourceId] | None = None
    visibility: AudioVisibility | None = None

    @model_validator(mode="after")
    def require_update(self) -> AudioUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one audio field is required")
        for name in ("title", "tag_ids", "visibility"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
