from __future__ import annotations

from datetime import datetime

from pydantic import Field

from backend.app.api.tag_schemas import TagApiModel
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.generation_batch import GenerationBatchStatus
from backend.app.integrations.llm import QuestionType


class GenerationBatchTagResponse(TagApiModel):
    id: int
    type: AudioTagType
    english_value: str


class GenerationBatchItemResponse(TagApiModel):
    id: int
    position: int = Field(ge=0)
    status: GenerationBatchStatus
    audio_id: int | None = None
    error_summary: str | None = None
    question_types: list[QuestionType] | None = None
    attempt_count: int = Field(ge=0)


class GenerationBatchSpeakerVoiceResponse(TagApiModel):
    speaker: str
    voice_id: int


class GenerationBatchResponse(TagApiModel):
    id: int
    job_id: int
    question_types: list[QuestionType]
    requested_count: int = Field(ge=1)
    status: GenerationBatchStatus
    tags: list[GenerationBatchTagResponse]
    items: list[GenerationBatchItemResponse]
    speaker_voices: list[GenerationBatchSpeakerVoiceResponse]
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class GenerationBatchAccepted(TagApiModel):
    batch_id: int
    job_id: int


class GenerationBatchRetryAccepted(TagApiModel):
    batch_id: int
    item_id: int
    job_id: int


class GenerationBatchListResponse(TagApiModel):
    items: list[GenerationBatchResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
