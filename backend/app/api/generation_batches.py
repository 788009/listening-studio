from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.api.generation_batch_schemas import (
    GenerationBatchAccepted,
    GenerationBatchAudioUpdate,
    GenerationBatchAudioUpdateResponse,
    GenerationBatchItemResponse,
    GenerationBatchListResponse,
    GenerationBatchResponse,
    GenerationBatchRetryAccepted,
    GenerationBatchSpeakerVoiceResponse,
    GenerationBatchTagResponse,
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
from backend.app.integrations.llm import QuestionType
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import GenerationBatchService
from backend.app.services.voice_storage import VoiceStorage


router = APIRouter(prefix="/api/generation-batches", tags=["generation-batches"])


def _service(request: Request) -> GenerationBatchService:
    settings = request.app.state.settings
    return GenerationBatchService(
        storage=CorpusStorage(settings.data_dir),
        voice_storage=VoiceStorage(settings.data_dir),
        audio_storage=AudioStorage(settings.data_dir),
        max_corpus_bytes=settings.max_corpus_bytes,
        max_generation_count=settings.max_batch_generation_count,
    )


def _response(batch: GenerationBatch) -> GenerationBatchResponse:
    return GenerationBatchResponse(
        id=batch.id,
        job_id=batch.job_id,
        question_types=[QuestionType(value) for value in batch.question_types],
        requested_count=batch.requested_count,
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
                audio_id=item.audio_id,
                error_summary=item.error_summary,
                question_types=_item_question_types(item.generated_content),
                attempt_count=item.attempt_count,
                title=item.audio.title if item.audio is not None else None,
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
    if not batch.items:
        return 0
    terminal = sum(
        item.status
        in {GenerationBatchStatus.COMPLETED, GenerationBatchStatus.FAILED}
        for item in batch.items
    )
    return terminal * 100 // len(batch.items)


def _item_question_types(
    content: dict[str, object] | None,
) -> list[QuestionType] | None:
    if content is None:
        return None
    values = content.get("question_types")
    if not isinstance(values, list):
        return None
    return [QuestionType(value) for value in values]


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


@router.post(
    "",
    response_model=GenerationBatchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_generation_batch(
    request: Request,
    question_types: Annotated[list[QuestionType], Form(alias="questionTypes")],
    count: Annotated[int, Form()],
    corpus: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
    encoding: Annotated[str | None, Form()] = None,
    tag_ids: Annotated[list[int] | None, Form(alias="tagIds")] = None,
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
            question_types=question_types,
            count=count,
            tag_ids=tag_ids or [],
            speaker_voice_map=_parse_speaker_voice_map(speaker_voice_map),
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
            question_types=question_types,
            count=count,
            tag_ids=tag_ids or [],
            speaker_voice_map=_parse_speaker_voice_map(speaker_voice_map),
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
    "/{batch_id}/items/{item_id}/retry",
    response_model=GenerationBatchRetryAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_generation_batch_item(
    batch_id: ResourceId,
    item_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationBatchRetryAccepted:
    submission = _service(request).retry_item(
        session,
        user,
        batch_id=batch_id,
        item_id=item_id,
    )
    return GenerationBatchRetryAccepted(
        batch_id=submission.batch.id,
        item_id=submission.item_id,
        job_id=submission.job.id,
    )


@router.patch(
    "/{batch_id}/completed-audios",
    response_model=GenerationBatchAudioUpdateResponse,
)
async def update_completed_batch_audios(
    batch_id: ResourceId,
    payload: GenerationBatchAudioUpdate,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> GenerationBatchAudioUpdateResponse:
    updated_count = _service(request).update_completed_audios(
        session,
        user,
        batch_id=batch_id,
        tag_ids=payload.tag_ids,
        visibility=payload.visibility,
    )
    return GenerationBatchAudioUpdateResponse(updated_count=updated_count)
