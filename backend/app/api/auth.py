from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict

from backend.app.core.exceptions import DomainValidationError
from backend.app.core.security import CSRF_COOKIE_NAME, issue_csrf_token
from backend.app.integrations.identity import (
    ExternalIdentity,
    IdentityProvider,
    LoginMethod,
    OidcAuthenticationError,
    OidcIdentityProvider,
    PlaceholderIdentityProvider,
)


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


def _oidc_provider(request: Request) -> OidcIdentityProvider:
    provider = _identity_provider(request)
    if not isinstance(provider, OidcIdentityProvider):
        raise HTTPException(status_code=404, detail="Not Found")
    return provider


def _set_identity_cookies(
    response: Response,
    request: Request,
    provider: IdentityProvider,
    identity: ExternalIdentity,
) -> None:
    token = provider.issue_session(identity)
    settings = request.app.state.settings
    response.set_cookie(
        settings.auth_session_cookie_name,
        token,
        max_age=settings.auth_session_max_age_seconds,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        issue_csrf_token(token, settings.auth_session_secret),
        max_age=settings.auth_session_max_age_seconds,
        httponly=False,
        secure=settings.environment == "production",
        samesite="lax",
    )


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

    response = Response(status_code=204)
    _set_identity_cookies(response, request, provider, identity)
    return response


@router.get("/oidc/login")
async def begin_oidc_login(request: Request) -> RedirectResponse:
    return await _oidc_provider(request).authorize_redirect(request)


@router.get("/oidc/callback")
async def complete_oidc_login(request: Request) -> RedirectResponse:
    provider = _oidc_provider(request)
    try:
        result = await provider.complete_authorization(request)
    except OidcAuthenticationError as exc:
        cause = exc.__cause__
        cause_name = type(cause).__name__ if cause else None
        cause_code = getattr(cause, "error", None) if cause else None
        logger.bind(request_id=request.state.request_id).warning(
            "OIDC authentication callback failed stage={} cause_type={} cause_code={}",
            str(exc),
            cause_name,
            cause_code,
        )
        raise HTTPException(status_code=400, detail="OIDC authentication failed")

    request.session.clear()
    logger.bind(request_id=request.state.request_id).info(
        "OIDC authentication completed claim_names={} userinfo_claim_names={} "
        "userinfo_subject_matches={}",
        list(result.claim_names),
        list(result.userinfo_claim_names),
        result.userinfo_subject_matches,
    )
    response = RedirectResponse(provider.post_login_url, status_code=303)
    _set_identity_cookies(response, request, provider, result.identity)
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
