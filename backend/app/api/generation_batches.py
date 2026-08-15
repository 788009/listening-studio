from __future__ import annotations

import asyncio
import json
from typing import Annotated
from unicodedata import normalize

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from loguru import logger
from sqlalchemy.orm import Session

from backend.app.api.generation_batch_schemas import (
    GenerationBatchAccepted,
    GenerationBatchItemResponse,
    GenerationBatchListResponse,
    GenerationBatchResponse,
    GenerationBatchSpeakerVoiceResponse,
    GenerationBatchTagResponse,
    GenerationDraftResponse,
    GenerationDraftRevisionRequest,
)
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import require_completed_profile
from backend.app.core.exceptions import DomainValidationError
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchStatus,
)
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.integrations.llm import (
    DashScopeLlmIntegration,
    DraftRevisionRequest,
    QuestionType,
)
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import GenerationBatchService
from backend.app.services.voice_storage import VoiceStorage


router = APIRouter(prefix="/api/generation-batches", tags=["generation-batches"])


def _service(request: Request) -> GenerationBatchService:
    settings = request.app.state.settings
    return GenerationBatchService(
        storage=CorpusStorage(settings.data_dir),
        voice_storage=VoiceStorage(settings.data_dir),
        max_corpus_bytes=settings.max_corpus_bytes,
        max_generation_count=settings.max_batch_generation_count,
    )


def _draft_reviser(request: Request) -> DashScopeLlmIntegration:
    existing = getattr(request.app.state, "draft_reviser", None)
    if existing is not None:
        return existing
    settings = request.app.state.settings
    if (
        settings.dashscope_api_key is None
        or not settings.dashscope_base_url
        or not settings.dashscope_model
    ):
        raise DomainValidationError("LLM settings are not configured")
    reviser = DashScopeLlmIntegration(
        api_key=settings.dashscope_api_key.get_secret_value(),
        base_url=settings.dashscope_base_url,
        model=settings.dashscope_model,
    )
    request.app.state.draft_reviser = reviser
    return reviser


def _response(batch: GenerationBatch) -> GenerationBatchResponse:
    return GenerationBatchResponse(
        id=batch.id,
        job_id=batch.job_id,
        question_type_counts={
            QuestionType(question_type): count
            for question_type, count in batch.question_type_counts.items()
        },
        status=batch.status,
        progress=_progress(batch),
        tags=[
            GenerationBatchTagResponse(
                id=tag.id,
                type=tag.type,
                english_value=tag.value,
            )
            for tag in batch.tags
        ],
        items=[
            GenerationBatchItemResponse(
                id=item.id,
                position=item.position,
                status=item.status,
                attempt_count=item.attempt_count,
                draft=(
                    GenerationDraftResponse.model_validate(item.generated_content)
                    if item.generated_content is not None
                    else None
                ),
                error_summary=item.error_summary,
            )
            for item in batch.items
        ],
        speaker_voices=[
            GenerationBatchSpeakerVoiceResponse(
                speaker=item.speaker,
                voice_id=item.voice_id,
            )
            for item in batch.speaker_voices
        ],
        error_summary=batch.error_summary,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _progress(batch: GenerationBatch) -> int:
    if batch.status is GenerationBatchStatus.COMPLETED:
        return 100
    if batch.status is GenerationBatchStatus.FAILED:
        return 100
    return batch.job.progress


def _parse_speaker_voice_map(value: str | None) -> dict[str, int]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "Speaker voice map must be valid JSON",
            details={"field": "speakerVoiceMap"},
        ) from exc
    if not isinstance(parsed, dict):
        raise DomainValidationError(
            "Speaker voice map must be an object",
            details={"field": "speakerVoiceMap"},
        )
    return parsed


def _parse_question_type(value: str) -> QuestionType:
    try:
        return QuestionType(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "Question type is invalid",
            details={"field": "questionType"},
        ) from exc


@router.post(
    "",
    response_model=GenerationBatchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation_batch(
    request: Request,
    question_type: Annotated[str, Form(alias="questionType")],
    count: Annotated[int, Form()],
    corpus: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    encoding: Annotated[str | None, Form()] = None,
    speaker_voice_map: Annotated[
        str | None,
        Form(alias="speakerVoiceMap"),
    ] = None,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationBatchAccepted:
    if (corpus is None) == (file is None):
        if file is not None:
            await file.close()
        raise DomainValidationError(
            "Provide exactly one corpus text or TXT file",
            details={"fields": ["corpus", "file"]},
        )
    service = _service(request)
    parsed_question_type = _parse_question_type(question_type)
    speaker_voices = _parse_speaker_voice_map(speaker_voice_map)
    if file is None:
        if encoding is not None:
            raise DomainValidationError(
                "Encoding is only valid for corpus files",
                details={"field": "encoding"},
            )
        submission = service.submit_text(
            session,
            owner=user,
            corpus=corpus or "",
            question_type=parsed_question_type,
            count=count,
            speaker_voice_map=speaker_voices,
            request_id=request.state.request_id,
        )
    else:
        content = await file.read(request.app.state.settings.max_corpus_bytes + 1)
        await file.close()
        submission = service.submit_file(
            session,
            owner=user,
            filename=file.filename or "",
            content=content,
            encoding=encoding or "",
            question_type=parsed_question_type,
            count=count,
            speaker_voice_map=speaker_voices,
            request_id=request.state.request_id,
        )
    return GenerationBatchAccepted(
        batch_id=submission.batch.id,
        job_id=submission.job.id,
    )


@router.get(
    "",
    response_model=GenerationBatchListResponse,
    response_model_exclude_none=True,
)
async def list_generation_batches(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationBatchListResponse:
    result = _service(request).list_owned(
        session,
        user,
        page=page,
        page_size=page_size,
    )
    return GenerationBatchListResponse(
        items=[_response(batch) for batch in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get(
    "/{batch_id}",
    response_model=GenerationBatchResponse,
    response_model_exclude_none=True,
)
async def get_generation_batch(
    batch_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationBatchResponse:
    return _response(_service(request).get_owned(session, user, batch_id))


@router.post(
    "/{batch_id}/revise-draft",
    response_model=GenerationDraftResponse,
)
async def revise_generation_draft(
    batch_id: ResourceId,
    payload: GenerationDraftRevisionRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationDraftResponse:
    logger.bind(
        request_id=request.state.request_id,
        resource_type="generation_batch",
        resource_id=batch_id,
    ).info("AI draft revision requested batch_id={}", batch_id)
    _service(request).get_owned(session, user, batch_id)
    revision_request = DraftRevisionRequest(
        prompt=payload.prompt,
        question_type=payload.draft.question_type,
        title=payload.draft.title,
        utterances=[
            {
                "speakerDisplayName": utterance.speaker_display_name,
                "text": utterance.text,
            }
            for utterance in payload.draft.utterances
        ],
        questions=[question.model_dump() for question in payload.draft.questions],
    )
    normalized_speakers: dict[str, tuple[str, int]] = {}
    speaker_voices: dict[str, int] = {}
    for utterance, source in zip(
        revision_request.utterances,
        payload.draft.utterances,
        strict=True,
    ):
        identity = normalize("NFKC", utterance.speaker_display_name).casefold()
        speaker = (utterance.speaker_display_name, source.voice_id)
        if identity in normalized_speakers and normalized_speakers[identity] != speaker:
            raise DomainValidationError("Draft speaker names must be unique")
        normalized_speakers[identity] = speaker
        speaker_voices[utterance.speaker_display_name] = source.voice_id
    revision = await asyncio.to_thread(
        _draft_reviser(request).revise_draft,
        revision_request,
        call_id=request.state.request_id,
    )
    logger.bind(
        request_id=request.state.request_id,
        resource_type="generation_batch",
        resource_id=batch_id,
    ).info("AI draft revision completed batch_id={}", batch_id)
    return GenerationDraftResponse(
        question_type=payload.draft.question_type,
        title=revision.title,
        utterances=[
            {
                "speakerDisplayName": utterance.speaker_display_name,
                "voiceId": speaker_voices[utterance.speaker_display_name],
                "text": utterance.text,
            }
            for utterance in revision.utterances
        ],
        questions=[question.model_dump() for question in revision.questions],
    )
