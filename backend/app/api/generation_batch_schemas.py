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


class GenerationDraftUtteranceResponse(TagApiModel):
    speaker_display_name: str
    voice_id: int
    text: str


class GenerationDraftQuestionResponse(TagApiModel):
    prompt: str
    correct_answers: list[str]
    incorrect_answers: list[str]


class GenerationDraftResponse(TagApiModel):
    question_type: QuestionType
    title: str
    utterances: list[GenerationDraftUtteranceResponse]
    questions: list[GenerationDraftQuestionResponse]


class GenerationBatchItemResponse(TagApiModel):
    id: int
    position: int = Field(ge=0)
    status: GenerationBatchStatus
    attempt_count: int = Field(ge=0)
    draft: GenerationDraftResponse | None = None
    error_summary: str | None = None


class GenerationBatchSpeakerVoiceResponse(TagApiModel):
    speaker: str
    voice_id: int


class GenerationBatchResponse(TagApiModel):
    id: int
    job_id: int
    question_type_counts: dict[QuestionType, int]
    status: GenerationBatchStatus
    progress: int = Field(ge=0, le=100)
    tags: list[GenerationBatchTagResponse]
    items: list[GenerationBatchItemResponse]
    speaker_voices: list[GenerationBatchSpeakerVoiceResponse]
    error_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class GenerationBatchAccepted(TagApiModel):
    batch_id: int
    job_id: int


class GenerationBatchListResponse(TagApiModel):
    items: list[GenerationBatchResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
