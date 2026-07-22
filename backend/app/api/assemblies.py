from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from loguru import logger
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from backend.app.api.assembly_schemas import (
    AssemblyAccepted,
    AssemblyCreateRequest,
    AssemblyPreviewAccepted,
    AssemblyPreviewRequest,
    AssemblySegmentRequest,
    AssemblyTemplateResponse,
    AssemblyTemplateSegmentResponse,
    AssemblyTemplateWriteRequest,
)
from backend.app.api.media import stream_wav
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import require_admin, require_completed_profile
from backend.app.core.exceptions import ConflictError
from backend.app.db.models.assembly import AssemblyTemplate
from backend.app.db.models.job import JobStatus
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.assemblies import AssemblySegmentInput, AssemblyService
from backend.app.services.audio_storage import AudioStorage


template_router = APIRouter(
    prefix="/api/assembly-templates",
    tags=["assembly-templates"],
)
router = APIRouter(prefix="/api/assemblies", tags=["assemblies"])
preview_router = APIRouter(
    prefix="/api/assembly-previews",
    tags=["assembly-previews"],
)
preview_media_router = APIRouter(
    prefix="/media/assembly-preview",
    tags=["media"],
)


def _service(request: Request) -> AssemblyService:
    return AssemblyService(AudioStorage(request.app.state.settings.data_dir))


def _input(item: AssemblySegmentRequest) -> AssemblySegmentInput:
    return AssemblySegmentInput(
        type=item.type,
        audio_id=item.audio_id,
        suggested_query=item.suggested_query,
        silence_milliseconds=item.silence_milliseconds,
        smart_mode=item.smart_mode,
        smart_silence_previous=item.smart_silence_previous,
        smart_silence_next=item.smart_silence_next,
        repeat_count=item.repeat_count,
        repeat_interval_milliseconds=item.repeat_interval_milliseconds,
        include_text=item.include_text,
        include_topic=item.include_topic,
    )


def _template_response(template: AssemblyTemplate) -> AssemblyTemplateResponse:
    return AssemblyTemplateResponse(
        id=template.id,
        title=template.title,
        owner_user_id=template.owner.user_id or "",
        segments=[
            AssemblyTemplateSegmentResponse(
                id=item.id,
                position=item.position,
                type=item.type,
                audio_id=item.audio_id,
                suggested_query=item.suggested_query,
                silence_milliseconds=item.silence_milliseconds,
                smart_mode=item.smart_mode,
                smart_silence_previous=item.smart_silence_previous,
                smart_silence_next=item.smart_silence_next,
                repeat_count=item.repeat_count,
                repeat_interval_milliseconds=item.repeat_interval_milliseconds,
                include_text=item.include_text,
                include_topic=item.include_topic,
            )
            for item in template.segments
        ],
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@template_router.get("", response_model=list[AssemblyTemplateResponse])
async def list_templates(
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> list[AssemblyTemplateResponse]:
    del user
    return [
        _template_response(item) for item in _service(request).list_templates(session)
    ]


@template_router.post(
    "",
    response_model=AssemblyTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: AssemblyTemplateWriteRequest,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> AssemblyTemplateResponse:
    template = _service(request).create_template(
        session,
        user,
        payload.title,
        [_input(item) for item in payload.segments],
    )
    return _template_response(template)


@template_router.put("/{template_id}", response_model=AssemblyTemplateResponse)
async def update_template(
    template_id: ResourceId,
    payload: AssemblyTemplateWriteRequest,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> AssemblyTemplateResponse:
    template = _service(request).update_template(
        session,
        user,
        template_id,
        payload.title,
        [_input(item) for item in payload.segments],
    )
    return _template_response(template)


@template_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: ResourceId,
    request: Request,
    user: User = Depends(require_admin),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete_template(session, user, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "",
    response_model=AssemblyAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_assembly(
    payload: AssemblyCreateRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AssemblyAccepted:
    submission = _service(request).submit(
        session,
        user,
        title=payload.title,
        segments=[_input(item) for item in payload.segments],
        tag_ids=payload.tag_ids,
        visibility=payload.visibility,
    )
    return AssemblyAccepted(audio_id=submission.audio.id, job_id=submission.job_id)


@preview_router.post(
    "",
    response_model=AssemblyPreviewAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_assembly_preview(
    payload: AssemblyPreviewRequest,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> AssemblyPreviewAccepted:
    submission = _service(request).submit_preview(
        session,
        user,
        segments=[_input(item) for item in payload.segments],
        start_index=payload.start_index,
        end_index=payload.end_index,
    )
    logger.bind(
        request_id=request.state.request_id,
        job_id=submission.job.id,
        user_db_id=user.id,
        resource_type="job",
        resource_id=submission.job.id,
    ).info("Assembly preview submitted job_id={}", submission.job.id)
    return AssemblyPreviewAccepted(job_id=submission.job.id)


@preview_router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assembly_preview(
    job_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> Response:
    _service(request).delete_preview(session, owner=user, job_id=job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@preview_media_router.get("/{job_id}")
async def play_assembly_preview(
    job_id: ResourceId,
    request: Request,
    user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    service = _service(request)
    job = service.get_owned_preview(session, user, job_id)
    if job.status is not JobStatus.SUCCEEDED:
        raise ConflictError("Assembly preview is not ready")
    return stream_wav(
        request,
        service.job_storage.assembly_preview_path(job.id),
        cache_control="private, no-store",
    )
