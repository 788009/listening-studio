from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from loguru import logger
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from backend.app.api.media import stream_wav
from backend.app.api.schemas import ResourceId
from backend.app.api.tag_schemas import (
    TagTranslationResponse,
    VoiceTagResponse,
)
from backend.app.api.voice_schemas import (
    VoiceAuthorResponse,
    VoiceListResponse,
    VoiceResponse,
    VoiceUpdateRequest,
    VoiceUploadAccepted,
)
from backend.app.core.auth import (
    Principal,
    get_principal,
    require_completed_profile,
)
from backend.app.core.locales import get_request_locale
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTag
from backend.app.db.session import get_db_session
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.job_storage import JobStorage
from backend.app.services.tag_values import select_tag_display_value
from backend.app.services.voice_management import VoiceManagementService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voice_uploads import VoiceUploadService


router = APIRouter(prefix="/api/voices", tags=["voices"])
media_router = APIRouter(prefix="/media/voice", tags=["media"])


def _service(request: Request) -> VoiceManagementService:
    data_dir = request.app.state.settings.data_dir
    return VoiceManagementService(
        VoiceStorage(data_dir),
        AudioStorage(data_dir),
    )


def _tag_response(tag: VoiceTag, language: str) -> VoiceTagResponse:
    translations = {
        translation.language: translation.value for translation in tag.translations
    }
    return VoiceTagResponse(
        id=tag.id,
        type=tag.type,
        english_value=tag.value,
        display_value=select_tag_display_value(tag.value, translations, language),
        full_tag=f"{tag.type.value}:{tag.value}",
        translations=[
            TagTranslationResponse(
                language=translation.language,
                value=translation.value,
            )
            for translation in tag.translations
        ],
    )


def _voice_response(
    voice: Voice,
    principal: Principal,
    language: str,
) -> VoiceResponse:
    is_owner = bool(principal.user and principal.user.id == voice.author_id)
    return VoiceResponse(
        id=voice.id,
        author=VoiceAuthorResponse(
            user_id=voice.author.user_id or "",
            username=voice.author.username,
        ),
        title=voice.title,
        status=voice.status,
        visibility=voice.visibility,
        sample_source=voice.sample_source,
        sample_audio_id=voice.sample_audio_id,
        error_summary=voice.error_summary if is_owner else None,
        tags=[_tag_response(tag, language) for tag in voice.tags],
    )


@router.post(
    "",
    response_model=VoiceUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_voice(
    request: Request,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    file: Annotated[UploadFile, File()],
    gender_tag_id: Annotated[int | None, Form(alias="genderTagId")] = None,
    visibility: Annotated[VoiceVisibility, Form()] = VoiceVisibility.PRIVATE,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> VoiceUploadAccepted:
    settings = request.app.state.settings
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    submission = VoiceUploadService(
        storage=VoiceStorage(settings.data_dir),
        max_upload_bytes=settings.max_upload_bytes,
        job_storage=JobStorage(settings.data_dir),
    ).prepare_async_upload(
        session,
        author=current_user,
        title=title,
        filename=file.filename or "",
        content=content,
        gender_tag_id=gender_tag_id,
        target_visibility=visibility,
    )
    logger.bind(
        request_id=request.state.request_id,
        job_id=submission.job.id,
        user_db_id=current_user.id,
        resource_type="voice",
        resource_id=submission.voice.id,
    ).info("Voice upload submitted")
    return VoiceUploadAccepted(
        voice_id=submission.voice.id,
        job_id=submission.job.id,
    )


@router.get("", response_model=VoiceListResponse, response_model_exclude_none=True)
async def list_voices(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    language: str = Depends(get_request_locale),
    author: str | None = Query(default=None, min_length=1, max_length=64),
    voice_status: VoiceStatus | None = Query(default=None, alias="status"),
    visibility: VoiceVisibility | None = Query(default=None),
    query: str | None = Query(default=None, alias="q", max_length=1024),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> VoiceListResponse:
    result = _service(request).list_visible(
        session,
        principal,
        page=page,
        page_size=page_size,
        author=author,
        status=voice_status,
        visibility=visibility,
        query=query,
    )
    return VoiceListResponse(
        items=[_voice_response(voice, principal, language) for voice in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.get(
    "/{voice_id}",
    response_model=VoiceResponse,
    response_model_exclude_none=True,
)
async def get_voice(
    voice_id: ResourceId,
    request: Request,
    language: str = Depends(get_request_locale),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> VoiceResponse:
    voice = _service(request).get_visible(session, principal, voice_id)
    return _voice_response(voice, principal, language)


@router.patch(
    "/{voice_id}",
    response_model=VoiceResponse,
    response_model_exclude_none=True,
)
async def update_voice(
    voice_id: ResourceId,
    payload: VoiceUpdateRequest,
    request: Request,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> VoiceResponse:
    principal = Principal(current_user)
    voice = _service(request).update(
        session,
        principal,
        voice_id,
        title=payload.title,
        gender_tag_ids=payload.gender_tag_ids,
        visibility=payload.visibility,
        sample_source=payload.sample_source,
        sample_audio_id=payload.sample_audio_id,
    )
    return _voice_response(voice, principal, current_user.locale)


@router.delete("/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(
    voice_id: ResourceId,
    request: Request,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete(
        session,
        Principal(current_user),
        voice_id,
        request_id=request.state.request_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@media_router.get("/{voice_id}/sample")
async def play_voice_sample(
    voice_id: ResourceId,
    request: Request,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    path = _service(request).resolve_sample_path(
        session,
        Principal(current_user),
        voice_id,
    )
    return stream_wav(
        request,
        path,
        cache_control="private, no-store",
    )
