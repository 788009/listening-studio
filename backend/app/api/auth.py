from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.core.exceptions import DomainValidationError
from backend.app.core.security import CSRF_COOKIE_NAME, issue_csrf_token
from backend.app.integrations.identity import IdentityProvider, LoginMethod
from backend.app.integrations.identity import PlaceholderIdentityProvider


router = APIRouter(prefix="/auth", tags=["authentication"])


def _to_camel(field_name: str) -> str:
    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


class AuthApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=_to_camel)


class AuthenticationCapabilitiesResponse(AuthApiModel):
    login_method: LoginMethod
    login_url: str | None


class DebugSessionRequest(AuthApiModel):
    issuer: str
    subject: str


class EndSessionResponse(AuthApiModel):
    redirect_url: str | None


def _identity_provider(request: Request) -> IdentityProvider:
    return request.app.state.identity_provider


def _placeholder_provider(request: Request) -> PlaceholderIdentityProvider:
    provider = _identity_provider(request)
    if not isinstance(provider, PlaceholderIdentityProvider) or not provider.enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    return provider


@router.get("/capabilities", response_model=AuthenticationCapabilitiesResponse)
async def get_authentication_capabilities(
    request: Request,
) -> AuthenticationCapabilitiesResponse:
    capabilities = _identity_provider(request).capabilities()
    return AuthenticationCapabilitiesResponse(
        login_method=capabilities.login_method.value,
        login_url=capabilities.login_url,
    )


@router.post("/debug/session", status_code=204)
async def create_debug_session(
    request: Request,
    payload: DebugSessionRequest | None = None,
) -> Response:
    provider = _placeholder_provider(request)
    identity = (
        provider.identity_from_values(payload.issuer, payload.subject)
        if payload is not None
        else provider.identity_from_headers(request)
    )
    if identity is None:
        raise DomainValidationError(
            "Debug issuer and subject are required",
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


@router.delete("/session", response_model=EndSessionResponse)
async def delete_session(request: Request) -> JSONResponse:
    redirect_url = await _identity_provider(request).end_session(request)
    response = JSONResponse(
        EndSessionResponse(redirect_url=redirect_url).model_dump(
            mode="json",
            by_alias=True,
        )
    )
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
