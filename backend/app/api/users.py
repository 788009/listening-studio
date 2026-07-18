from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from backend.app.core.auth import (
    Principal,
    get_principal,
    require_completed_profile,
    require_teacher,
)
from backend.app.core.exceptions import NotFoundError
from backend.app.core.locales import SupportedLocale
from backend.app.db.models.user import User
from backend.app.db.session import get_db_session
from backend.app.repositories.users import UserRepository
from backend.app.services.users import UserService


router = APIRouter(prefix="/api/users", tags=["users"])


def _to_camel(field_name: str) -> str:
    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=_to_camel,
        extra="forbid",
    )


class CompleteProfileRequest(ApiModel):
    user_id: str
    username: str | None = None
    locale: SupportedLocale | None = None


class UpdateProfileRequest(ApiModel):
    username: str | None = None
    locale: SupportedLocale | None = None

    @model_validator(mode="after")
    def require_update(self) -> UpdateProfileRequest:
        if self.username is None and self.locale is None:
            raise ValueError("At least one profile field is required")
        return self


class CurrentUserResponse(ApiModel):
    user_id: str | None
    username: str | None
    locale: str
    profile_complete: bool


class PublicStatistics(ApiModel):
    public_voice_count: int = 0
    public_audio_count: int = 0


class PrivateStatistics(ApiModel):
    private_voice_count: int = 0
    private_audio_count: int = 0


class UserSummaryResponse(ApiModel):
    user_id: str
    username: str | None
    locale: str
    created_at: datetime
    statistics: PublicStatistics
    private_statistics: PrivateStatistics | None = None


def _attached_user(session: Session, current_user: User) -> User:
    user = UserRepository().get_by_id(session, current_user.id)
    if user is None:
        raise NotFoundError("Current user no longer exists")
    return user


def _current_user_response(user: User) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=user.user_id,
        username=user.username,
        locale=user.locale,
        profile_complete=user.is_profile_complete,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user(
    current_user: User = Depends(require_teacher),
) -> CurrentUserResponse:
    return _current_user_response(current_user)


@router.post("/me/profile", response_model=CurrentUserResponse)
async def complete_profile(
    payload: CompleteProfileRequest,
    request: Request,
    current_user: User = Depends(require_teacher),
    session: Session = Depends(get_db_session),
) -> CurrentUserResponse:
    user = _attached_user(session, current_user)
    service = UserService()
    service.set_user_id(session, user, payload.user_id)
    if payload.username is not None:
        service.update_username(session, user, payload.username)
    if payload.locale is not None:
        service.update_locale(session, user, payload.locale)
    logger.bind(
        request_id=request.state.request_id,
        user_db_id=user.id,
        resource_type="user",
        resource_id=user.id,
    ).info(
        "User profile completed user_db_id={}", user.id
    )
    return _current_user_response(user)


@router.patch("/me/profile", response_model=CurrentUserResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    request: Request,
    current_user: User = Depends(require_completed_profile),
    session: Session = Depends(get_db_session),
) -> CurrentUserResponse:
    user = _attached_user(session, current_user)
    service = UserService()
    if payload.username is not None:
        service.update_username(session, user, payload.username)
    if payload.locale is not None:
        service.update_locale(session, user, payload.locale)
    logger.bind(
        request_id=request.state.request_id,
        user_db_id=user.id,
        resource_type="user",
        resource_id=user.id,
    ).info(
        "User profile updated user_db_id={}", user.id
    )
    return _current_user_response(user)


@router.get(
    "/{user_id}",
    response_model=UserSummaryResponse,
    response_model_exclude_none=True,
)
async def get_user_summary(
    user_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db_session),
) -> UserSummaryResponse:
    repository = UserRepository()
    user = repository.get_by_user_id(session, user_id)
    if user is None or user.user_id is None:
        raise NotFoundError("User not found")

    is_current_user = bool(principal.user and principal.user.id == user.id)
    resource_statistics = repository.resource_statistics(session, user.id)
    return UserSummaryResponse(
        user_id=user.user_id,
        username=user.username,
        locale=user.locale,
        created_at=user.created_at,
        statistics=PublicStatistics(
            public_voice_count=resource_statistics.public_voice_count,
            public_audio_count=resource_statistics.public_audio_count,
        ),
        private_statistics=(
            PrivateStatistics(
                private_voice_count=resource_statistics.private_voice_count,
                private_audio_count=resource_statistics.private_audio_count,
            )
            if is_current_user
            else None
        ),
    )
