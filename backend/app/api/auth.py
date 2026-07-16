from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from backend.app.core.exceptions import DomainValidationError
from backend.app.core.security import CSRF_COOKIE_NAME, issue_csrf_token
from backend.app.integrations.identity import PlaceholderIdentityProvider


router = APIRouter(prefix="/auth", tags=["authentication"])


def _placeholder_provider(request: Request) -> PlaceholderIdentityProvider:
    provider = request.app.state.identity_provider
    if not isinstance(provider, PlaceholderIdentityProvider) or not provider.enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    return provider


@router.post("/debug/session", status_code=204)
async def create_debug_session(request: Request) -> Response:
    provider = _placeholder_provider(request)
    identity = provider.identity_from_headers(request)
    if identity is None:
        raise DomainValidationError(
            "Debug issuer and subject headers are required",
            details={"fields": ["issuer", "subject"]},
        )

    token = provider.issue_session(identity)
    response = Response(status_code=204)
    response.set_cookie(
        provider.cookie_name,
        token,
        max_age=provider.max_age_seconds,
        httponly=True,
        secure=request.app.state.settings.environment == "production",
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        issue_csrf_token(token, request.app.state.settings.auth_session_secret),
        max_age=provider.max_age_seconds,
        httponly=False,
        secure=request.app.state.settings.environment == "production",
        samesite="lax",
    )
    return response


@router.delete("/session", status_code=204)
async def delete_session(request: Request) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(
        request.app.state.settings.auth_session_cookie_name,
        httponly=True,
        secure=request.app.state.settings.environment == "production",
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        secure=request.app.state.settings.environment == "production",
        samesite="lax",
    )
    return response
