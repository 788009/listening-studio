from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from backend.app.core.config import Settings


DEBUG_ISSUER_HEADER = "X-Debug-OIDC-Issuer"
DEBUG_SUBJECT_HEADER = "X-Debug-OIDC-Subject"


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str


class IdentityProvider(Protocol):
    async def authenticate(self, request: Request) -> ExternalIdentity | None:
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


class PlaceholderIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.debug_auth_enabled
        self.cookie_name = settings.auth_session_cookie_name
        self.max_age_seconds = settings.auth_session_max_age_seconds
        self._secret = settings.auth_session_secret.get_secret_value().encode("utf-8")

    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        if not self.enabled:
            return None

        header_identity = self.identity_from_headers(request)
        if header_identity:
            return header_identity

        token = request.cookies.get(self.cookie_name)
        return self.verify_session(token) if token else None

    def identity_from_headers(self, request: Request) -> ExternalIdentity | None:
        issuer = request.headers.get(DEBUG_ISSUER_HEADER)
        subject = request.headers.get(DEBUG_SUBJECT_HEADER)
        if issuer is None or subject is None:
            return None
        return self._validated_identity(issuer, subject)

    def issue_session(
        self,
        identity: ExternalIdentity,
        *,
        now: int | None = None,
    ) -> str:
        issued_at = int(time.time()) if now is None else now
        payload = json.dumps(
            {
                "issuer": identity.issuer,
                "subject": identity.subject,
                "expires_at": issued_at + self.max_age_seconds,
            },
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
            return self._validated_identity(payload["issuer"], payload["subject"])
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
