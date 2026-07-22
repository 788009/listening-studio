from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from backend.app.api.schemas import ResourceId, Title
from backend.app.api.tag_schemas import TagApiModel
from backend.app.db.models.assembly import AssemblySegmentType
from backend.app.db.models.audio import AudioVisibility


class AssemblySegmentRequest(TagApiModel):
    type: AssemblySegmentType
    audio_id: ResourceId | None = None
    suggested_query: str | None = Field(default=None, max_length=1024)
    silence_milliseconds: int = Field(default=0, ge=0, le=60_000)
    repeat_count: int = Field(default=1, ge=1, le=10)
    repeat_interval_milliseconds: int = Field(default=0, ge=0, le=60_000)
    include_text: bool = True
    include_topic: bool = True

    @model_validator(mode="after")
    def validate_kind(self) -> AssemblySegmentRequest:
        if self.type in {AssemblySegmentType.AUDIO, AssemblySegmentType.PLACEHOLDER}:
            if self.type is AssemblySegmentType.AUDIO and self.audio_id is None:
                raise ValueError("Audio segments require audioId")
        elif self.audio_id is not None:
            raise ValueError("This segment type does not accept audioId")
        if self.type is not AssemblySegmentType.SILENCE and self.silence_milliseconds:
            raise ValueError("Only silence segments accept silenceMilliseconds")
        return self


class AssemblyTemplateWriteRequest(TagApiModel):
    title: Title
    segments: list[AssemblySegmentRequest] = Field(min_length=1, max_length=40)


class AssemblyTemplateSegmentResponse(AssemblySegmentRequest):
    id: int
    position: int


class AssemblyTemplateResponse(TagApiModel):
    id: int
    title: str
    owner_user_id: str
    segments: list[AssemblyTemplateSegmentResponse]
    created_at: datetime
    updated_at: datetime


class AssemblyCreateRequest(TagApiModel):
    title: Title
    template_id: ResourceId | None = None
    segments: list[AssemblySegmentRequest] = Field(min_length=1, max_length=40)
    tag_ids: list[ResourceId] = Field(default_factory=list)
    visibility: AudioVisibility = AudioVisibility.PRIVATE


class AssemblyAccepted(TagApiModel):
    audio_id: int
    job_id: int
