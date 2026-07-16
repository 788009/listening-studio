from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session

from backend.app.api.schemas import LanguageCode, ResourceId
from backend.app.api.tag_schemas import (
    AudioTagCreate,
    AudioTagResponse,
    TagTranslationCreate,
    TagTranslationResponse,
    TagTranslationUpdate,
    VoiceTagCreate,
    VoiceTagResponse,
)
from backend.app.core.auth import Principal, get_principal, require_completed_profile
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.user import User
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.db.session import get_db_session
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.tag_autocomplete import (
    MAX_AUTOCOMPLETE_QUERY_LENGTH,
    MAX_AUTOCOMPLETE_RESULTS,
)
from backend.app.services.tag_values import (
    TagTranslationInput,
    select_tag_display_value,
)
from backend.app.services.voice_tags import VoiceTagService
from backend.app.services.voice_storage import VoiceStorage


voice_router = APIRouter(prefix="/api/voice-tags", tags=["voice-tags"])
audio_router = APIRouter(prefix="/api/audio-tags", tags=["audio-tags"])


def _translation_inputs(
    translations: list[TagTranslationCreate],
) -> list[TagTranslationInput]:
    return [
        TagTranslationInput(language=item.language, value=item.value)
        for item in translations
    ]


def _translation_responses(tag: VoiceTag | AudioTag) -> list[TagTranslationResponse]:
    return [
        TagTranslationResponse(
            language=translation.language,
            value=translation.value,
        )
        for translation in tag.translations
    ]


def _display_value(tag: VoiceTag | AudioTag, language: str) -> str:
    translations = {
        translation.language: translation.value for translation in tag.translations
    }
    return select_tag_display_value(tag.value, translations, language)


def _voice_response(tag: VoiceTag, language: str) -> VoiceTagResponse:
    return VoiceTagResponse(
        id=tag.id,
        type=tag.type,
        english_value=tag.value,
        display_value=_display_value(tag, language),
        full_tag=f"{tag.type.value}:{tag.value}",
        translations=_translation_responses(tag),
    )


def _audio_response(tag: AudioTag, language: str) -> AudioTagResponse:
    return AudioTagResponse(
        id=tag.id,
        type=tag.type,
        english_value=tag.value,
        display_value=_display_value(tag, language),
        full_tag=f"{tag.type.value}:{tag.value}",
        translations=_translation_responses(tag),
    )


@voice_router.post(
    "",
    response_model=VoiceTagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_tag(
    payload: VoiceTagCreate,
    request: Request,
    language: LanguageCode = Query(default="en"),
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> VoiceTagResponse:
    tag = VoiceTagService().create_user_tag(
        session,
        tag_type=payload.type,
        english_value=payload.value,
        translations=_translation_inputs(payload.translations),
    )
    logger.bind(request_id=request.state.request_id).info(
        "Voice tag created tag_id={} tag_type={}", tag.id, tag.type.value
    )
    return _voice_response(tag, language)


@voice_router.get("", response_model=list[VoiceTagResponse])
async def list_voice_tags(
    language: LanguageCode = Query(default="en"),
    tag_type: VoiceTagType | None = Query(default=None, alias="type"),
    session: Session = Depends(get_db_session),
) -> list[VoiceTagResponse]:
    tags = VoiceTagService().list_tags(session, tag_type)
    return [_voice_response(tag, language) for tag in tags]


@voice_router.get("/autocomplete", response_model=list[str])
async def autocomplete_voice_tags(
    request: Request,
    query: str = Query(
        alias="q",
        min_length=1,
        max_length=MAX_AUTOCOMPLETE_QUERY_LENGTH,
    ),
    limit: int = Query(default=10, ge=1, le=MAX_AUTOCOMPLETE_RESULTS),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[str]:
    storage = VoiceStorage(request.app.state.settings.data_dir)
    return VoiceTagService().autocomplete(
        session,
        query=query,
        limit=limit,
        principal=principal,
        storage=storage,
    )


@voice_router.get("/{tag_id}", response_model=VoiceTagResponse)
async def get_voice_tag(
    tag_id: ResourceId,
    language: LanguageCode = Query(default="en"),
    session: Session = Depends(get_db_session),
) -> VoiceTagResponse:
    tag = VoiceTagService().get_tag(session, tag_id)
    return _voice_response(tag, language)


@voice_router.put(
    "/{tag_id}/translations/{language}",
    response_model=VoiceTagResponse,
)
async def upsert_voice_tag_translation(
    tag_id: ResourceId,
    language: LanguageCode,
    payload: TagTranslationUpdate,
    request: Request,
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> VoiceTagResponse:
    tag = VoiceTagService().upsert_translation(
        session,
        tag_id=tag_id,
        translation=TagTranslationInput(language=language, value=payload.value),
    )
    logger.bind(request_id=request.state.request_id).info(
        "Voice tag translation updated tag_id={} language={}", tag.id, language
    )
    return _voice_response(tag, language)


@voice_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice_tag(
    tag_id: ResourceId,
    request: Request,
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    VoiceTagService().delete_tag(session, tag_id)
    logger.bind(request_id=request.state.request_id).info(
        "Voice tag deleted tag_id={}", tag_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@audio_router.post(
    "",
    response_model=AudioTagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_audio_tag(
    payload: AudioTagCreate,
    request: Request,
    language: LanguageCode = Query(default="en"),
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioTagResponse:
    tag = AudioTagService().create_user_tag(
        session,
        tag_type=payload.type,
        english_value=payload.value,
        translations=_translation_inputs(payload.translations),
    )
    logger.bind(request_id=request.state.request_id).info(
        "Audio tag created tag_id={} tag_type={}", tag.id, tag.type.value
    )
    return _audio_response(tag, language)


@audio_router.get("", response_model=list[AudioTagResponse])
async def list_audio_tags(
    language: LanguageCode = Query(default="en"),
    tag_type: AudioTagType | None = Query(default=None, alias="type"),
    session: Session = Depends(get_db_session),
) -> list[AudioTagResponse]:
    tags = AudioTagService().list_tags(session, tag_type)
    return [_audio_response(tag, language) for tag in tags]


@audio_router.get("/autocomplete", response_model=list[str])
async def autocomplete_audio_tags(
    request: Request,
    query: str = Query(
        alias="q",
        min_length=1,
        max_length=MAX_AUTOCOMPLETE_QUERY_LENGTH,
    ),
    limit: int = Query(default=10, ge=1, le=MAX_AUTOCOMPLETE_RESULTS),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> list[str]:
    storage = AudioStorage(request.app.state.settings.data_dir)
    return AudioTagService().autocomplete(
        session,
        query=query,
        limit=limit,
        principal=principal,
        storage=storage,
    )


@audio_router.get("/{tag_id}", response_model=AudioTagResponse)
async def get_audio_tag(
    tag_id: ResourceId,
    language: LanguageCode = Query(default="en"),
    session: Session = Depends(get_db_session),
) -> AudioTagResponse:
    tag = AudioTagService().get_tag(session, tag_id)
    return _audio_response(tag, language)


@audio_router.put(
    "/{tag_id}/translations/{language}",
    response_model=AudioTagResponse,
)
async def upsert_audio_tag_translation(
    tag_id: ResourceId,
    language: LanguageCode,
    payload: TagTranslationUpdate,
    request: Request,
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AudioTagResponse:
    tag = AudioTagService().upsert_translation(
        session,
        tag_id=tag_id,
        translation=TagTranslationInput(language=language, value=payload.value),
    )
    logger.bind(request_id=request.state.request_id).info(
        "Audio tag translation updated tag_id={} language={}", tag.id, language
    )
    return _audio_response(tag, language)


@audio_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audio_tag(
    tag_id: ResourceId,
    request: Request,
    _current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    AudioTagService().delete_tag(session, tag_id)
    logger.bind(request_id=request.state.request_id).info(
        "Audio tag deleted tag_id={}", tag_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
