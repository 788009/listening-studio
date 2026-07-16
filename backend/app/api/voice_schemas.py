from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.api.schemas import ResourceId, Title
from backend.app.api.tag_schemas import VoiceTagResponse
from backend.app.db.models.voice import (
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)


def _to_camel(field_name: str) -> str:
    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class VoiceApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
        extra="forbid",
    )


class VoiceAuthorResponse(VoiceApiModel):
    user_id: str
    username: str | None


class VoiceResponse(VoiceApiModel):
    id: int
    author: VoiceAuthorResponse
    title: str
    status: VoiceStatus
    visibility: VoiceVisibility
    sample_source: VoiceSampleSource
    sample_audio_id: int | None
    error_summary: str | None = None
    tags: list[VoiceTagResponse]


class VoiceListResponse(VoiceApiModel):
    items: list[VoiceResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class VoiceUpdateRequest(VoiceApiModel):
    title: Title | None = None
    gender_tag_ids: list[ResourceId] | None = None
    visibility: VoiceVisibility | None = None
    sample_source: VoiceSampleSource | None = None
    sample_audio_id: ResourceId | None = None

    @model_validator(mode="after")
    def require_update(self) -> VoiceUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one voice field is required")
        for field_name in (
            "title",
            "gender_tag_ids",
            "visibility",
            "sample_source",
        ):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        source_set = "sample_source" in self.model_fields_set
        audio_id_set = "sample_audio_id" in self.model_fields_set
        if audio_id_set and not source_set:
            raise ValueError("sample_source is required with sample_audio_id")
        if source_set:
            if self.sample_source is VoiceSampleSource.ORIGINAL:
                if audio_id_set and self.sample_audio_id is not None:
                    raise ValueError("original samples cannot specify sample_audio_id")
            elif not audio_id_set or self.sample_audio_id is None:
                raise ValueError("public_audio samples require sample_audio_id")
        return self


class VoiceUploadAccepted(VoiceApiModel):
    voice_id: int
    job_id: int
