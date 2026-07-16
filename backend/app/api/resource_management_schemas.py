from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from backend.app.api.schemas import ResourceId
from backend.app.api.tag_schemas import TagApiModel
from backend.app.services.resource_management import (
    BulkOutcome,
    ManagedResourceKind,
)


class ManagedTagResponse(TagApiModel):
    id: int
    type: str
    value: str


class ManagedReferenceResponse(TagApiModel):
    type: str
    count: int = Field(ge=1)


class ManagedResourceResponse(TagApiModel):
    id: int
    kind: ManagedResourceKind
    title: str
    status: str
    visibility: str | None = None
    tags: list[ManagedTagResponse]
    created_at: datetime
    references: list[ManagedReferenceResponse]
    can_delete: bool


class ManagedResourceListResponse(TagApiModel):
    items: list[ManagedResourceResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class BulkResourceUpdateRequest(TagApiModel):
    kind: ManagedResourceKind
    resource_ids: list[ResourceId] = Field(min_length=1, max_length=100)
    visibility: Literal["private", "public"] | None = None
    tag_ids: list[ResourceId] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_update(self) -> BulkResourceUpdateRequest:
        if len(set(self.resource_ids)) != len(self.resource_ids):
            raise ValueError("Resource IDs must be unique")
        if self.tag_ids is not None and len(set(self.tag_ids)) != len(self.tag_ids):
            raise ValueError("Tag IDs must be unique")
        if self.visibility is None and self.tag_ids is None:
            raise ValueError("At least one bulk update field is required")
        return self


class BulkItemResultResponse(TagApiModel):
    id: int
    outcome: BulkOutcome
    message: str


class BulkResourceUpdateResponse(TagApiModel):
    items: list[BulkItemResultResponse]
    success_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
