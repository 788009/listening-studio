from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from backend.app.api.audio_schemas import (
    AudioPreviewAccepted,
    AudioPreviewRequest,
    AudioPublishFromPreviewsRequest,
    AudioResponse,
)
from backend.app.api.audios import _response
from backend.app.api.media import stream_wav
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import Principal, require_completed_profile
from backend.app.core.exceptions import ConflictError
from backend.app.db.models.job import JobStatus
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.audio_previews import (
    AudioPreviewService,
    PublishedAudioUtterance,
)
from backend.app.services.audios import AudioQuestionInput
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.job_storage import JobStorage
from backend.app.services.voice_storage import VoiceStorage


router = APIRouter(prefix="/api/audio-previews", tags=["audio-previews"])
publish_router = APIRouter(prefix="/api/audios", tags=["audios"])
media_router = APIRouter(prefix="/media/audio-preview", tags=["media"])


def _service(request: Request, *, publishing: bool = False) -> AudioPreviewService:
    settings = request.app.state.settings
    return AudioPreviewService(
        job_storage=JobStorage(settings.data_dir),
        voice_storage=VoiceStorage(settings.data_dir),
        audio_storage=AudioStorage(settings.data_dir) if publishing else None,
    )


@router.post(
    "", response_model=AudioPreviewAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def create_audio_preview(
    payload: AudioPreviewRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioPreviewAccepted:
    submission = _service(request).submit(
        session,
        owner=user,
        voice_id=payload.voice_id,
        speaker_display_name=payload.speaker_display_name,
        text=payload.text,
    )
    logger.bind(
        request_id=request.state.request_id,
        job_id=submission.job.id,
        user_db_id=user.id,
        resource_type="job",
        resource_id=submission.job.id,
    ).info("Audio preview submitted job_id={}", submission.job.id)
    return AudioPreviewAccepted(
        job_id=submission.job.id,
        content_digest=submission.content_digest,
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio_preview(
    job_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete(session, owner=user, job_id=job_id)
    return Response(status_code=204)


@publish_router.post(
    "/from-previews",
    response_model=AudioResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
)
async def publish_audio_from_previews(
    payload: AudioPublishFromPreviewsRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioResponse:
    audio = _service(request, publishing=True).publish(
        session,
        author=user,
        title=payload.title,
        utterances=[
            PublishedAudioUtterance(
                preview_job_id=item.preview_job_id,
                voice_id=item.voice_id,
                speaker_display_name=item.speaker_display_name,
                text=item.text,
            )
            for item in payload.utterances
        ],
        tag_ids=payload.tag_ids,
        questions=[
            AudioQuestionInput(
                item.prompt,
                tuple(item.correct_answers),
                tuple(item.incorrect_answers),
            )
            for item in payload.questions
        ],
        visibility=payload.visibility,
        silence_milliseconds=request.app.state.settings.dialogue_silence_milliseconds,
    )
    logger.bind(
        request_id=request.state.request_id,
        user_db_id=user.id,
        resource_type="audio",
        resource_id=audio.id,
    ).info("Audio published from previews audio_id={}", audio.id)
    return _response(audio, Principal(user), user.locale)


@media_router.get("/{job_id}")
async def play_audio_preview(
    job_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    service = _service(request)
    job = service.get_owned_preview(session, user, job_id)
    if job.status is not JobStatus.SUCCEEDED:
        raise ConflictError("Audio preview is not ready")
    return stream_wav(
        request,
        service.job_storage.audio_preview_path(job.id),
        cache_control="private, no-store",
    )
