from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from backend.app.api.schemas import ResourceId, Title
from backend.app.api.tag_schemas import TagApiModel
from backend.app.db.models.assembly import AssemblySegmentType, AssemblySmartMode
from backend.app.db.models.audio import AudioVisibility


class AssemblySegmentRequest(TagApiModel):
    type: AssemblySegmentType
    audio_id: ResourceId | None = None
    suggested_query: str | None = Field(default=None, max_length=1024)
    comment_text: str | None = None
    silence_milliseconds: int = Field(default=0, ge=0, le=60_000)
    smart_mode: AssemblySmartMode = AssemblySmartMode.QUESTION_NUMBER
    smart_silence_previous: bool = False
    smart_silence_next: bool = False
    repeat_count: int = Field(default=1, ge=1, le=10)
    repeat_interval_milliseconds: int = Field(default=0, ge=0, le=60_000)
    include_text: bool = True
    include_topic: bool = True

    @model_validator(mode="after")
    def validate_kind(self) -> AssemblySegmentRequest:
        is_comment = self.type is AssemblySegmentType.COMMENT
        if self.type in {AssemblySegmentType.AUDIO, AssemblySegmentType.PLACEHOLDER}:
            if self.type is AssemblySegmentType.AUDIO and self.audio_id is None:
                raise ValueError("Audio segments require audioId")
        elif self.audio_id is not None:
            raise ValueError("This segment type does not accept audioId")
        if is_comment:
            if self.comment_text is None or not self.comment_text.strip():
                raise ValueError("Comment segments require commentText")
            self.comment_text = self.comment_text.strip()
        elif self.comment_text is not None:
            raise ValueError("Only comment segments accept commentText")
        is_smart_silence = (
            self.type is AssemblySegmentType.SMART
            and self.smart_mode is AssemblySmartMode.QUESTION_COUNT_SILENCE
        )
        if (
            self.type is not AssemblySegmentType.SILENCE
            and not is_smart_silence
            and self.silence_milliseconds
        ):
            raise ValueError("Only silence segments accept silenceMilliseconds")
        if is_smart_silence and (
            self.smart_silence_previous == self.smart_silence_next
        ):
            raise ValueError("Question-count silence requires exactly one associated segment")
        if self.smart_mode is AssemblySmartMode.QUESTION_NUMBER and (
            self.smart_silence_previous or self.smart_silence_next
        ):
            raise ValueError("Question-number audio does not accept silence associations")
        return self


class AssemblyTemplateWriteRequest(TagApiModel):
    title: Title
    segments: list[AssemblySegmentRequest] = Field(min_length=1)


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
    segments: list[AssemblySegmentRequest] = Field(min_length=1)
    tag_ids: list[ResourceId] = Field(default_factory=list)
    visibility: AudioVisibility = AudioVisibility.PRIVATE


class AssemblyAccepted(TagApiModel):
    audio_id: int
    job_id: int


class AssemblyPreviewRequest(TagApiModel):
    segments: list[AssemblySegmentRequest] = Field(min_length=1)
    start_index: int = Field(ge=0)
    end_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> AssemblyPreviewRequest:
        end_index = self.end_index if self.end_index is not None else len(self.segments) - 1
        if self.start_index >= len(self.segments) or end_index >= len(self.segments):
            raise ValueError("Preview range is outside the segment list")
        if end_index < self.start_index:
            raise ValueError("Preview end index must not precede its start index")
        return self


class AssemblyPreviewAccepted(TagApiModel):
    job_id: int
