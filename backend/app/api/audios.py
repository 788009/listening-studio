from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from backend.app.api.audio_schemas import (
    AudioAuthorResponse,
    AudioListResponse,
    AudioResponse,
    AudioSynthesisAccepted,
    AudioSynthesisRequest,
    AudioUpdateRequest,
    AudioUtteranceResponse,
    DialogueSynthesisRequest,
)
from backend.app.api.media import stream_wav
from backend.app.api.schemas import LanguageCode, ResourceId
from backend.app.api.tag_schemas import AudioTagResponse, TagTranslationResponse
from backend.app.core.auth import Principal, get_principal, require_completed_profile
from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.audio_tag import AudioTag
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.audio_management import AudioManagementService
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioUtteranceInput
from backend.app.services.tag_values import select_tag_display_value
from backend.app.services.voice_storage import VoiceStorage


router = APIRouter(prefix="/api/audios", tags=["audios"])
media_router = APIRouter(prefix="/media/audio", tags=["media"])


def _service(request: Request) -> AudioManagementService:
    return AudioManagementService(AudioStorage(request.app.state.settings.data_dir))


def _tag(tag: AudioTag, language: str) -> AudioTagResponse:
    translations = {item.language: item.value for item in tag.translations}
    return AudioTagResponse(
        id=tag.id,
        type=tag.type,
        english_value=tag.value,
        display_value=select_tag_display_value(tag.value, translations, language),
        full_tag=f"{tag.type.value}:{tag.value}",
        translations=[
            TagTranslationResponse(language=item.language, value=item.value)
            for item in tag.translations
        ],
    )


def _response(audio: Audio, principal: Principal, language: str) -> AudioResponse:
    owner = bool(principal.user and principal.user.id == audio.author_id)
    return AudioResponse(
        id=audio.id,
        author=AudioAuthorResponse(
            user_id=audio.author.user_id or "",
            username=audio.author.username,
        ),
        title=audio.title,
        text=audio.text,
        source_type=audio.source_type,
        status=audio.status,
        visibility=audio.visibility,
        duration_seconds=audio.duration_seconds,
        sample_rate=audio.sample_rate,
        error_summary=audio.error_summary if owner else None,
        tags=[_tag(tag, language) for tag in audio.tags],
        utterances=[
            AudioUtteranceResponse(
                voice_id=item.voice_id,
                speaker_display_name=item.speaker_display_name,
                text=item.text,
                position=item.position,
            )
            for item in audio.utterances
        ],
    )


@router.post(
    "",
    response_model=AudioSynthesisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audio(
    payload: AudioSynthesisRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioSynthesisAccepted:
    settings = request.app.state.settings
    submission = AudioSynthesisService(
        audio_storage=AudioStorage(settings.data_dir),
        voice_storage=VoiceStorage(settings.data_dir),
    ).prepare_single_speaker(
        session,
        author=user,
        title=payload.title,
        text=payload.text,
        voice_id=payload.voice_id,
        tag_ids=payload.tag_ids,
        target_visibility=payload.visibility,
    )
    return AudioSynthesisAccepted(
        audio_id=submission.audio.id,
        job_id=submission.job.id,
    )


@router.post(
    "/dialogues",
    response_model=AudioSynthesisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_dialogue(
    payload: DialogueSynthesisRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioSynthesisAccepted:
    settings = request.app.state.settings
    submission = AudioSynthesisService(
        audio_storage=AudioStorage(settings.data_dir),
        voice_storage=VoiceStorage(settings.data_dir),
    ).prepare_dialogue(
        session,
        author=user,
        title=payload.title,
        utterances=[
            AudioUtteranceInput(
                voice_id=item.voice_id,
                speaker_display_name=item.speaker_display_name,
                text=item.text,
            )
            for item in payload.utterances
        ],
        tag_ids=payload.tag_ids,
        target_visibility=payload.visibility,
        silence_milliseconds=settings.dialogue_silence_milliseconds,
    )
    return AudioSynthesisAccepted(
        audio_id=submission.audio.id,
        job_id=submission.job.id,
    )


@router.get("", response_model=AudioListResponse, response_model_exclude_none=True)
async def list_audios(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    language: LanguageCode = Query(default="en"),
    author: str | None = Query(default=None, min_length=1, max_length=64),
    audio_status: AudioStatus | None = Query(default=None, alias="status"),
    visibility: AudioVisibility | None = Query(default=None),
    query: str | None = Query(default=None, alias="q", max_length=1024),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> AudioListResponse:
    result = _service(request).list_visible(
        session,
        principal,
        page=page,
        page_size=page_size,
        author=author,
        status=audio_status,
        visibility=visibility,
        query=query,
    )
    return AudioListResponse(
        items=[_response(item, principal, language) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get(
    "/{audio_id}",
    response_model=AudioResponse,
    response_model_exclude_none=True,
)
async def get_audio(
    audio_id: ResourceId,
    request: Request,
    language: LanguageCode = Query(default="en"),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> AudioResponse:
    audio = _service(request).get_visible(session, principal, audio_id)
    return _response(audio, principal, language)


@router.patch(
    "/{audio_id}",
    response_model=AudioResponse,
    response_model_exclude_none=True,
)
async def update_audio(
    audio_id: ResourceId,
    payload: AudioUpdateRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioResponse:
    principal = Principal(user)
    audio = _service(request).update(
        session,
        principal,
        audio_id,
        title=payload.title,
        tag_ids=payload.tag_ids,
        visibility=payload.visibility,
    )
    return _response(audio, principal, user.locale)


@router.delete("/{audio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio(
    audio_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete(
        session,
        Principal(user),
        audio_id,
        request_id=request.state.request_id,
    )
    return Response(status_code=204)


@media_router.get("/{audio_id}")
async def play_audio(
    audio_id: ResourceId,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    audio = _service(request).get_visible(session, principal, audio_id)
    return stream_wav(
        request,
        AudioStorage(request.app.state.settings.data_dir).path(audio.id),
        cache_control=(
            "public, max-age=3600"
            if audio.visibility is AudioVisibility.PUBLIC
            else "private, no-store"
        ),
    )
