from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.core.exceptions import ForbiddenError
from backend.app.db.models.user import User
from backend.app.integrations.identity import IdentityProvider
from backend.app.services.users import UserService


@dataclass(frozen=True)
class Principal:
    user: User | None = None

    @property
    def is_teacher(self) -> bool:
        return self.user is not None

    @property
    def has_completed_profile(self) -> bool:
        return bool(self.user and self.user.is_profile_complete)


STUDENT_PRINCIPAL = Principal()


class AuthenticationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        identity_provider: IdentityProvider,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.app = app
        self.identity_provider = identity_provider
        self.session_factory = session_factory
        self.user_service = UserService()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        external_identity = await self.identity_provider.authenticate(request)
        user = None
        if external_identity:
            with self.session_factory() as session:
                user = self.user_service.get_or_create_pending_user(
                    session,
                    issuer=external_identity.issuer,
                    subject=external_identity.subject,
                )
                session.commit()

        principal = Principal(user=user)
        state = scope.setdefault("state", {})
        state["principal"] = principal
        state["current_user"] = user
        await self.app(scope, receive, send)


async def get_principal(request: Request) -> Principal:
    return getattr(request.state, "principal", STUDENT_PRINCIPAL)


async def require_teacher(
    principal: Principal = Depends(get_principal),
) -> User:
    if principal.user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal.user


async def require_completed_profile(
    user: User = Depends(require_teacher),
) -> User:
    if not user.is_profile_complete:
        raise ForbiddenError("Profile setup is required")
    return user
