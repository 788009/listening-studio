from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from backend.app.api.resource_management_schemas import (
    BulkItemResultResponse,
    BulkResourceUpdateRequest,
    BulkResourceUpdateResponse,
    ManagedAuthorResponse,
    ManagedReferenceResponse,
    ManagedResourceListResponse,
    ManagedResourceResponse,
    ManagedTagResponse,
)
from backend.app.api.schemas import ResourceId
from backend.app.core.auth import require_completed_profile
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.services.resource_management import (
    ManagedResource,
    ManagedResourceKind,
    ResourceManagementService,
)


router = APIRouter(prefix="/api/resource-management", tags=["resource-management"])


def _service(request: Request) -> ResourceManagementService:
    return ResourceManagementService(request.app.state.settings.data_dir)


def _response(item: ManagedResource, owner: User) -> ManagedResourceResponse:
    assert owner.user_id is not None
    return ManagedResourceResponse(
        id=item.id,
        kind=item.kind,
        author=ManagedAuthorResponse(
            user_id=owner.user_id,
            username=owner.username,
        ),
        title=item.title,
        status=item.status,
        visibility=item.visibility,
        tags=[
            ManagedTagResponse(id=tag.id, type=tag.type, value=tag.value)
            for tag in item.tags
        ],
        created_at=item.created_at,
        references=[
            ManagedReferenceResponse(type=value.type, count=value.count)
            for value in item.references
        ],
        can_delete=item.can_delete,
    )


@router.get(
    "",
    response_model=ManagedResourceListResponse,
    response_model_exclude_none=True,
)
async def list_managed_resources(
    request: Request,
    kind: ManagedResourceKind = Query(),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    resource_status: str | None = Query(default=None, alias="status", max_length=16),
    visibility: str | None = Query(default=None, max_length=16),
    tag_ids: Annotated[list[ResourceId] | None, Query(alias="tagId")] = None,
    created_from: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    query: str | None = Query(default=None, alias="q", max_length=200),
    owner: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> ManagedResourceListResponse:
    result = _service(request).list_owned(
        session,
        owner,
        kind=kind,
        page=page,
        page_size=page_size,
        status=resource_status,
        visibility=visibility,
        tag_ids=tag_ids or [],
        created_from=created_from,
        created_before=created_before,
        query=query,
    )
    return ManagedResourceListResponse(
        items=[_response(item, owner) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


@router.post("/bulk-update", response_model=BulkResourceUpdateResponse)
async def bulk_update_managed_resources(
    payload: BulkResourceUpdateRequest,
    request: Request,
    owner: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> BulkResourceUpdateResponse:
    result = _service(request).bulk_update(
        session,
        owner,
        kind=payload.kind,
        resource_ids=payload.resource_ids,
        visibility=payload.visibility,
        tag_ids=payload.tag_ids,
        request_id=request.state.request_id,
    )
    return BulkResourceUpdateResponse(
        items=[
            BulkItemResultResponse(
                id=item.id,
                outcome=item.outcome,
                message=item.message,
            )
            for item in result.items
        ],
        success_count=result.success_count,
        conflict_count=result.conflict_count,
        failed_count=result.failed_count,
    )
