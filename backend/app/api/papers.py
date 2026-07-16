from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.api.paper_schemas import (
    PaperCreateRequest,
    PaperItemResponse,
    PaperListResponse,
    PaperPresetResponse,
    PaperPresetWriteRequest,
    PaperResponse,
)
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import require_completed_profile
from backend.app.db.models.paper import Paper, PaperPreset
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.papers import PaperPresetParameters, PaperService


preset_router = APIRouter(prefix="/api/paper-presets", tags=["paper-presets"])
paper_router = APIRouter(prefix="/api/papers", tags=["papers"])


def _service(request: Request) -> PaperService:
    return PaperService(AudioStorage(request.app.state.settings.data_dir))


def _parameters(payload: PaperPresetWriteRequest) -> PaperPresetParameters:
    return PaperPresetParameters(
        intro_silence_milliseconds=payload.intro_silence_milliseconds,
        inter_item_silence_milliseconds=payload.inter_item_silence_milliseconds,
        repeat_count=payload.repeat_count,
        outro_silence_milliseconds=payload.outro_silence_milliseconds,
    )


def _preset_response(preset: PaperPreset) -> PaperPresetResponse:
    return PaperPresetResponse(
        id=preset.id,
        name=preset.name,
        is_builtin=preset.is_builtin,
        intro_silence_milliseconds=preset.intro_silence_milliseconds,
        inter_item_silence_milliseconds=preset.inter_item_silence_milliseconds,
        repeat_count=preset.repeat_count,
        outro_silence_milliseconds=preset.outro_silence_milliseconds,
    )


def _paper_response(paper: Paper) -> PaperResponse:
    return PaperResponse(
        id=paper.id,
        title=paper.title,
        status=paper.status,
        preset_id=paper.preset_id,
        preset_name=paper.preset.name if paper.preset is not None else None,
        intro_silence_milliseconds=paper.intro_silence_milliseconds,
        inter_item_silence_milliseconds=paper.inter_item_silence_milliseconds,
        repeat_count=paper.repeat_count,
        outro_silence_milliseconds=paper.outro_silence_milliseconds,
        result_audio_id=paper.result_audio_id,
        error_summary=paper.error_summary,
        items=[
            PaperItemResponse(
                id=item.id,
                audio_id=item.audio_id,
                title=item.audio.title,
                position=item.position,
            )
            for item in paper.items
        ],
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@preset_router.get("", response_model=list[PaperPresetResponse])
async def list_paper_presets(
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> list[PaperPresetResponse]:
    return [
        _preset_response(item)
        for item in _service(request).list_presets(session, user)
    ]


@preset_router.post(
    "",
    response_model=PaperPresetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_paper_preset(
    payload: PaperPresetWriteRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> PaperPresetResponse:
    preset = _service(request).create_preset(
        session,
        user,
        name=payload.name,
        parameters=_parameters(payload),
    )
    return _preset_response(preset)


@preset_router.put("/{preset_id}", response_model=PaperPresetResponse)
async def update_paper_preset(
    preset_id: ResourceId,
    payload: PaperPresetWriteRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> PaperPresetResponse:
    preset = _service(request).update_preset(
        session,
        user,
        preset_id,
        name=payload.name,
        parameters=_parameters(payload),
    )
    return _preset_response(preset)


@preset_router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper_preset(
    preset_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete_preset(session, user, preset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@paper_router.post(
    "",
    response_model=PaperResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_paper(
    payload: PaperCreateRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> PaperResponse:
    paper = _service(request).create_paper(
        session,
        user,
        title=payload.title,
        preset_id=payload.preset_id,
        audio_ids=payload.audio_ids,
    )
    return _paper_response(paper)


@paper_router.get(
    "",
    response_model=PaperListResponse,
    response_model_exclude_none=True,
)
async def list_papers(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> PaperListResponse:
    result = _service(request).list_owned(
        session,
        user,
        page=page,
        page_size=page_size,
    )
    return PaperListResponse(
        items=[_paper_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@paper_router.get(
    "/{paper_id}",
    response_model=PaperResponse,
    response_model_exclude_none=True,
)
async def get_paper(
    paper_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> PaperResponse:
    return _paper_response(_service(request).get_owned(session, user, paper_id))
