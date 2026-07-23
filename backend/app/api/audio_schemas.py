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
    voice_id: int | None
    voice_title: str | None
    voice_tag: str | None
    speaker_display_name: str | None
    text: str
    position: int


class AudioQuestionRequest(TagApiModel):
    prompt: str = Field(min_length=1)
    correct_answers: list[str] = Field(min_length=1)
    incorrect_answers: list[str] = Field(min_length=1)


class AudioQuestionResponse(AudioQuestionRequest):
    id: int
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
    questions: list[AudioQuestionResponse]


class AudioListResponse(TagApiModel):
    items: list[AudioResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class AudioCreationDraftUtteranceResponse(TagApiModel):
    voice_id: int | None
    speaker_display_name: str
    text: str


class AudioCreationDraftResponse(TagApiModel):
    source_audio_id: int
    title: str
    text: str
    utterances: list[AudioCreationDraftUtteranceResponse]
    tag_ids: list[int]
    questions: list[AudioQuestionRequest]


class AudioSynthesisRequest(TagApiModel):
    title: Title
    text: str = Field(min_length=1)
    voice_id: ResourceId
    speaker_display_name: str | None = Field(default=None, min_length=1, max_length=200)
    tag_ids: list[ResourceId] = Field(default_factory=list)
    questions: list[AudioQuestionRequest] = Field(default_factory=list)
    visibility: AudioVisibility = AudioVisibility.PRIVATE


class AudioSynthesisAccepted(TagApiModel):
    audio_id: int
    job_id: int


class DialogueUtteranceRequest(TagApiModel):
    voice_id: ResourceId
    speaker_display_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class DialogueSynthesisRequest(TagApiModel):
    title: Title
    utterances: list[DialogueUtteranceRequest] = Field(min_length=1)
    tag_ids: list[ResourceId] = Field(default_factory=list)
    questions: list[AudioQuestionRequest] = Field(default_factory=list)
    visibility: AudioVisibility = AudioVisibility.PRIVATE


class AudioPreviewRequest(TagApiModel):
    voice_id: ResourceId
    speaker_display_name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)


class AudioPreviewAccepted(TagApiModel):
    job_id: int
    content_digest: str


class PreviewAudioUtteranceRequest(DialogueUtteranceRequest):
    preview_job_id: ResourceId


class AudioPublishFromPreviewsRequest(TagApiModel):
    title: Title
    utterances: list[PreviewAudioUtteranceRequest] = Field(min_length=1)
    tag_ids: list[ResourceId] = Field(default_factory=list)
    questions: list[AudioQuestionRequest] = Field(default_factory=list)
    visibility: AudioVisibility = AudioVisibility.PRIVATE


class AudioUpdateRequest(TagApiModel):
    title: Title | None = None
    tag_ids: list[ResourceId] | None = None
    visibility: AudioVisibility | None = None
    questions: list[AudioQuestionRequest] | None = None

    @model_validator(mode="after")
    def require_update(self) -> AudioUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("At least one audio field is required")
        for name in ("title", "tag_ids", "visibility", "questions"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
