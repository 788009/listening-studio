from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from fastapi import Request
from joserfc.errors import JoseError
from starlette.responses import RedirectResponse

from backend.app.core.config import Settings


DEBUG_ISSUER_HEADER = "X-Debug-OIDC-Issuer"
DEBUG_SUBJECT_HEADER = "X-Debug-OIDC-Subject"


def _normalize_token_response(response: httpx.Response) -> httpx.Response:
    try:
        payload = response.json()
    except ValueError:
        return response
    if not isinstance(payload, dict):
        return response

    candidate = payload.get("data")
    if not isinstance(candidate, dict):
        candidate = payload
    if not isinstance(candidate.get("access_token"), str):
        return response
    if payload.get("error") not in {None, ""} or candidate.get("error") not in {
        None,
        "",
    }:
        return response

    normalized = dict(candidate)
    normalized.pop("error", None)
    return httpx.Response(
        status_code=response.status_code,
        json=normalized,
        request=response.request,
    )


def _configure_oidc_client(client: AsyncOAuth2Client) -> None:
    client.register_compliance_hook("access_token_response", _normalize_token_response)


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str
    suggested_username: str | None = None


class LoginMethod(str, Enum):
    NONE = "none"
    DEBUG = "debug"
    REDIRECT = "redirect"


@dataclass(frozen=True)
class IdentityProviderCapabilities:
    login_method: LoginMethod
    login_url: str | None = None


class IdentityProvider(Protocol):
    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        pass

    def capabilities(self) -> IdentityProviderCapabilities:
        pass

    def issue_session(self, identity: ExternalIdentity) -> str:
        pass

    async def end_session(self, request: Request) -> str | None:
        """End the provider session and return an optional browser redirect URL."""
        pass


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )


def _validated_suggested_username(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        return None
    return normalized


class PlaceholderIdentityProvider:
    def __init__(self, settings: Settings, *, session_kind: str = "debug") -> None:
        self.enabled = settings.debug_auth_enabled
        self.cookie_name = settings.auth_session_cookie_name
        self.max_age_seconds = settings.auth_session_max_age_seconds
        self.session_kind = session_kind
        self._secret = settings.auth_session_secret.get_secret_value().encode("utf-8")

    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        if not self.enabled:
            return None

        header_identity = self.identity_from_headers(request)
        if header_identity:
            return header_identity

        token = request.cookies.get(self.cookie_name)
        return self.verify_session(token) if token else None

    def capabilities(self) -> IdentityProviderCapabilities:
        return IdentityProviderCapabilities(
            login_method=LoginMethod.DEBUG if self.enabled else LoginMethod.NONE
        )

    async def end_session(self, request: Request) -> str | None:
        del request
        return None

    def identity_from_headers(self, request: Request) -> ExternalIdentity | None:
        issuer = request.headers.get(DEBUG_ISSUER_HEADER)
        subject = request.headers.get(DEBUG_SUBJECT_HEADER)
        if issuer is None or subject is None:
            return None
        return self.identity_from_values(issuer, subject)

    def identity_from_values(
        self,
        issuer: object,
        subject: object,
    ) -> ExternalIdentity | None:
        return self._validated_identity(issuer, subject)

    def issue_session(
        self,
        identity: ExternalIdentity,
        *,
        now: int | None = None,
    ) -> str:
        issued_at = int(time.time()) if now is None else now
        session_payload: dict[str, object] = {
            "issuer": identity.issuer,
            "subject": identity.subject,
            "session_kind": self.session_kind,
            "expires_at": issued_at + self.max_age_seconds,
        }
        if identity.suggested_username is not None:
            session_payload["suggested_username"] = identity.suggested_username
        payload = json.dumps(
            session_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded_payload = _encode_base64(payload)
        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_encode_base64(signature)}"

    def verify_session(
        self,
        token: str,
        *,
        now: int | None = None,
    ) -> ExternalIdentity | None:
        try:
            encoded_payload, encoded_signature = token.split(".", maxsplit=1)
            supplied_signature = _decode_base64(encoded_signature)
            expected_signature = hmac.new(
                self._secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return None

            payload = json.loads(_decode_base64(encoded_payload))
            expires_at = payload["expires_at"]
            current_time = int(time.time()) if now is None else now
            if not isinstance(expires_at, int) or expires_at <= current_time:
                return None
            if payload.get("session_kind") != self.session_kind:
                return None
            identity = self._validated_identity(payload["issuer"], payload["subject"])
            if identity is None:
                return None
            suggested_username = _validated_suggested_username(
                payload.get("suggested_username")
            )
            return ExternalIdentity(
                issuer=identity.issuer,
                subject=identity.subject,
                suggested_username=suggested_username,
            )
        except (
            AttributeError,
            binascii.Error,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _validated_identity(issuer: object, subject: object) -> ExternalIdentity | None:
        if not isinstance(issuer, str) or not isinstance(subject, str):
            return None
        if not issuer.strip() or not subject.strip():
            return None
        if len(issuer) > 2048 or len(subject) > 255:
            return None
        return ExternalIdentity(issuer=issuer, subject=subject)


class OidcAuthenticationError(Exception):
    pass


@dataclass(frozen=True)
class OidcAuthorizationResult:
    identity: ExternalIdentity
    claim_names: tuple[str, ...]
    userinfo_claim_names: tuple[str, ...] = ()
    userinfo_subject_matches: bool | None = None


class OidcIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.oidc_enabled:
            raise ValueError("OIDC provider requires OIDC to be enabled")
        assert settings.oidc_discovery_url is not None
        assert settings.oidc_client_id is not None
        assert settings.oidc_client_secret is not None
        assert settings.oidc_redirect_uri is not None

        self.cookie_name = settings.auth_session_cookie_name
        self.max_age_seconds = settings.auth_session_max_age_seconds
        self.redirect_uri = settings.oidc_redirect_uri
        redirect = urlsplit(self.redirect_uri)
        self.login_url = urlunsplit(
            (redirect.scheme, redirect.netloc, "/auth/oidc/login", "", "")
        )
        self.post_login_url = settings.oidc_post_login_url
        self._session_provider = PlaceholderIdentityProvider(
            settings,
            session_kind="oidc",
        )
        client_kwargs = {
            "scope": settings.oidc_scopes,
            "token_endpoint_auth_method": settings.oidc_token_endpoint_auth_method,
        }
        if settings.oidc_pkce_enabled:
            client_kwargs["code_challenge_method"] = "S256"

        oauth = OAuth()
        oauth.register(
            name="oidc",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret.get_secret_value(),
            server_metadata_url=settings.oidc_discovery_url,
            client_kwargs=client_kwargs,
            compliance_fix=_configure_oidc_client,
        )
        client = oauth.create_client("oidc")
        if not isinstance(client, StarletteOAuth2App):
            raise RuntimeError("OIDC client could not be initialized")
        self._client = client

    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        token = request.cookies.get(self.cookie_name)
        return self.verify_session(token) if token else None

    def capabilities(self) -> IdentityProviderCapabilities:
        return IdentityProviderCapabilities(
            login_method=LoginMethod.REDIRECT,
            login_url=self.login_url,
        )

    def issue_session(self, identity: ExternalIdentity) -> str:
        return self._session_provider.issue_session(identity)

    def verify_session(self, token: str) -> ExternalIdentity | None:
        return self._session_provider.verify_session(token)

    async def authorize_redirect(self, request: Request) -> RedirectResponse:
        return await self._client.authorize_redirect(request, self.redirect_uri)

    async def complete_authorization(
        self,
        request: Request,
    ) -> OidcAuthorizationResult:
        try:
            token = await self._client.authorize_access_token(request)
        except (
            OAuthError,
            JoseError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            raise OidcAuthenticationError(
                "OIDC token exchange or ID token validation failed"
            ) from exc

        try:
            id_token_claims = token.get("userinfo")
            if not isinstance(id_token_claims, dict):
                if token.get("id_token") is not None:
                    raise OidcAuthenticationError("OIDC ID token was not validated")
                raise OidcAuthenticationError("OIDC response did not include an ID token")

            issuer = id_token_claims.get("iss")
            subject = id_token_claims.get("sub")
            identity = self._validated_identity(issuer, subject)
            if identity is None:
                raise OidcAuthenticationError("OIDC identity claims are invalid")
            identity = ExternalIdentity(
                issuer=identity.issuer,
                subject=identity.subject,
                suggested_username=_validated_suggested_username(
                    id_token_claims.get("name")
                ),
            )
            claim_names = set(id_token_claims)

            try:
                if token.get("token_type") is None:
                    userinfo_endpoint = self._client.server_metadata.get(
                        "userinfo_endpoint"
                    )
                    access_token = token.get("access_token")
                    if not isinstance(userinfo_endpoint, str):
                        raise OidcAuthenticationError(
                            "OIDC discovery metadata has no UserInfo endpoint"
                        )
                    if not isinstance(access_token, str):
                        raise OidcAuthenticationError("OIDC access token is missing")
                    response = await self._client.get(
                        userinfo_endpoint,
                        headers={"Authorization": f"Bearer {access_token}"},
                        withhold_token=True,
                        follow_redirects=False,
                    )
                    response.raise_for_status()
                    userinfo = response.json()
                    if not isinstance(userinfo, dict):
                        raise TypeError("OIDC UserInfo response must be an object")
                else:
                    userinfo = await self._client.userinfo(token=token)
            except (
                OAuthError,
                JoseError,
                httpx.HTTPError,
                ValueError,
                TypeError,
            ):
                userinfo = None

            if isinstance(userinfo, dict):
                userinfo_subject = userinfo.get("sub")
                userinfo_subject_matches = userinfo_subject == identity.subject
                if userinfo_subject_matches:
                    claim_names.update(userinfo)
                userinfo_claim_names = tuple(sorted(userinfo))
            else:
                userinfo_subject_matches = None
                userinfo_claim_names = ()

            return OidcAuthorizationResult(
                identity=identity,
                claim_names=tuple(sorted(claim_names)),
                userinfo_claim_names=userinfo_claim_names,
                userinfo_subject_matches=userinfo_subject_matches,
            )
        except OidcAuthenticationError:
            raise
        except (
            OAuthError,
            JoseError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            raise OidcAuthenticationError("OIDC response processing failed") from exc

    async def end_session(self, request: Request) -> str | None:
        del request
        return None

    @staticmethod
    def _validated_identity(issuer: object, subject: object) -> ExternalIdentity | None:
        return PlaceholderIdentityProvider._validated_identity(issuer, subject)
