from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from backend.app.db.models.user import User


class AuthorizationPrincipal(Protocol):
    user: User | None

    @property
    def is_teacher(self) -> bool:
        pass


class ResourceKind(str, Enum):
    AUDIO = "audio"
    VOICE = "voice"


class ResourceVisibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class ResourceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class ResourceDescriptor:
    kind: ResourceKind
    author_id: int
    visibility: ResourceVisibility
    status: ResourceStatus
    file_exists: bool


class AuthorizationService:
    @staticmethod
    def _is_owner(
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        return bool(
            principal.user is not None
            and principal.user.id == resource.author_id
        )

    @staticmethod
    def _is_playable(resource: ResourceDescriptor) -> bool:
        return resource.status is ResourceStatus.READY and resource.file_exists

    def can_view(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        if self._is_owner(principal, resource):
            return True
        if resource.visibility is not ResourceVisibility.PUBLIC:
            return False
        if not self._is_playable(resource):
            return False
        if principal.is_teacher:
            return True
        return resource.kind is ResourceKind.AUDIO

    def can_edit(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        return self._is_owner(principal, resource)

    def can_delete(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        return self.can_edit(principal, resource)

    def can_publish(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        return self._is_owner(principal, resource) and self._is_playable(resource)

    def can_use_as_example(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        return bool(
            principal.is_teacher
            and resource.kind is ResourceKind.AUDIO
            and resource.visibility is ResourceVisibility.PUBLIC
            and self._is_playable(resource)
        )

    def can_use_for_synthesis(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> bool:
        if not principal.is_teacher or resource.kind is not ResourceKind.VOICE:
            return False
        if not self._is_playable(resource):
            return False
        return self._is_owner(principal, resource) or (
            resource.visibility is ResourceVisibility.PUBLIC
        )

    def require_view(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if not self.can_view(principal, resource):
            raise NotFoundError("Resource not found")

    def require_edit(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if self.can_edit(principal, resource):
            return
        self._raise_hidden_or_forbidden(resource)

    def require_delete(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if self.can_delete(principal, resource):
            return
        self._raise_hidden_or_forbidden(resource)

    def require_publish(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if not self._is_owner(principal, resource):
            self._raise_hidden_or_forbidden(resource)
        if not self._is_playable(resource):
            raise ConflictError("Only ready resources with files can be public")

    def require_use_as_example(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if self.can_use_as_example(principal, resource):
            return
        if not principal.is_teacher:
            raise ForbiddenError("Teacher access is required")
        if (
            resource.visibility is ResourceVisibility.PRIVATE
            and not self._is_owner(principal, resource)
        ):
            raise NotFoundError("Resource not found")
        raise ConflictError("Example audio must be public and ready")

    def require_use_for_synthesis(
        self,
        principal: AuthorizationPrincipal,
        resource: ResourceDescriptor,
    ) -> None:
        if self.can_use_for_synthesis(principal, resource):
            return
        if not principal.is_teacher:
            raise ForbiddenError("Teacher access is required")
        if (
            resource.visibility is ResourceVisibility.PRIVATE
            and not self._is_owner(principal, resource)
        ):
            raise NotFoundError("Resource not found")
        raise ConflictError("Voice must be ready and available for synthesis")

    @staticmethod
    def _raise_hidden_or_forbidden(resource: ResourceDescriptor) -> None:
        if resource.visibility is ResourceVisibility.PUBLIC:
            raise ForbiddenError("Resource is owned by another teacher")
        raise NotFoundError("Resource not found")
