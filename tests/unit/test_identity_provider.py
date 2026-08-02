from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import httpx
from starlette.requests import Request

from backend.app.core.config import Settings
from backend.app.integrations.identity import (
    ExternalIdentity,
    LoginMethod,
    OidcAuthenticationError,
    OidcIdentityProvider,
    PlaceholderIdentityProvider,
    _normalize_token_response,
)


class PlaceholderIdentityProviderTest(unittest.TestCase):
    @staticmethod
    def provider() -> PlaceholderIdentityProvider:
        settings = Settings(
            _env_file=None,
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            auth_session_max_age_seconds=60,
            cosyvoice_model_dir=Path("/models/cosyvoice"),
        )
        return PlaceholderIdentityProvider(settings)

    def test_signed_session_round_trip(self) -> None:
        provider = self.provider()
        identity = ExternalIdentity("https://issuer.example", "teacher-1")

        token = provider.issue_session(identity, now=100)

        self.assertEqual(provider.verify_session(token, now=159), identity)
        self.assertIsNone(provider.verify_session(token, now=160))

    def test_tampered_session_is_rejected(self) -> None:
        provider = self.provider()
        token = provider.issue_session(
            ExternalIdentity("https://issuer.example", "teacher-1"),
            now=100,
        )
        payload, signature = token.split(".", maxsplit=1)
        tampered_token = f"{payload[:-1]}A.{signature}"

        self.assertIsNone(provider.verify_session(tampered_token, now=101))
        self.assertIsNone(provider.verify_session("invalid", now=101))

    def test_sessions_are_scoped_to_authentication_method(self) -> None:
        settings = Settings(
            _env_file=None,
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=Path("/models/cosyvoice"),
        )
        debug_provider = PlaceholderIdentityProvider(settings)
        oidc_session_provider = PlaceholderIdentityProvider(
            settings,
            session_kind="oidc",
        )
        identity = ExternalIdentity("https://issuer.example", "teacher-1")

        debug_token = debug_provider.issue_session(identity, now=100)
        oidc_token = oidc_session_provider.issue_session(identity, now=100)

        self.assertIsNone(oidc_session_provider.verify_session(debug_token, now=101))
        self.assertIsNone(debug_provider.verify_session(oidc_token, now=101))

    def test_capabilities_follow_debug_auth_setting(self) -> None:
        enabled = self.provider().capabilities()
        disabled_settings = Settings(
            _env_file=None,
            debug_auth_enabled=False,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=Path("/models/cosyvoice"),
        )
        disabled = PlaceholderIdentityProvider(disabled_settings).capabilities()

        self.assertEqual(enabled.login_method, LoginMethod.DEBUG)
        self.assertEqual(disabled.login_method, LoginMethod.NONE)
        self.assertIsNone(enabled.login_url)


class FakeOidcClient:
    def __init__(self, *, userinfo_subject: str = "oidc-user") -> None:
        self.userinfo_subject = userinfo_subject
        self.server_metadata = {
            "issuer": "https://issuer.example",
            "userinfo_endpoint": "https://issuer.example/userinfo",
        }

    async def authorize_access_token(self, request: Request) -> dict[str, Any]:
        del request
        return {
            "access_token": "test-access-token",
            "userinfo": {
                "iss": "https://issuer.example",
                "sub": "oidc-user",
                "aud": "client-id",
            },
        }

    async def userinfo(self, **kwargs: object) -> dict[str, object]:
        del kwargs
        return {
            "sub": self.userinfo_subject,
            "name": "Teacher One",
            "email_verified": True,
        }

    async def get(self, url: str, **kwargs: object) -> FakeHttpResponse:
        self.assert_userinfo_request(url, kwargs)
        return FakeHttpResponse(self.userinfo_subject)

    @staticmethod
    def assert_userinfo_request(url: str, kwargs: dict[str, object]) -> None:
        if url != "https://issuer.example/userinfo":
            raise AssertionError("Unexpected UserInfo URL")
        headers = kwargs.get("headers")
        if headers != {"Authorization": "Bearer test-access-token"}:
            raise AssertionError("UserInfo request did not use a Bearer token")


class FakeHttpResponse:
    def __init__(self, subject: str) -> None:
        self.subject = subject

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return {
            "sub": self.subject,
            "name": "Teacher One",
            "email_verified": True,
        }


class OidcIdentityProviderTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def provider() -> OidcIdentityProvider:
        settings = Settings(
            _env_file=None,
            debug_auth_enabled=False,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=Path("/models/cosyvoice"),
            oidc_enabled=True,
            oidc_discovery_url=(
                "https://issuer.example/.well-known/openid-configuration"
            ),
            oidc_client_id="client-id",
            oidc_client_secret="client-secret",
            oidc_redirect_uri="http://127.0.0.1:8000/auth/oidc/callback",
        )
        return OidcIdentityProvider(settings)

    async def test_validated_identity_and_userinfo_claim_names(self) -> None:
        provider = self.provider()
        provider._client = FakeOidcClient()  # type: ignore[assignment]
        request = Request({"type": "http", "method": "GET", "path": "/"})

        result = await provider.complete_authorization(request)
        token = provider.issue_session(result.identity)

        self.assertEqual(
            result.identity,
            ExternalIdentity("https://issuer.example", "oidc-user"),
        )
        self.assertEqual(
            result.claim_names,
            ("aud", "email_verified", "iss", "name", "sub"),
        )
        self.assertEqual(provider.verify_session(token), result.identity)
        self.assertEqual(provider.capabilities().login_method, LoginMethod.REDIRECT)

    async def test_mismatched_userinfo_is_not_merged_with_id_token(self) -> None:
        provider = self.provider()
        provider._client = FakeOidcClient(  # type: ignore[assignment]
            userinfo_subject="different-user"
        )
        request = Request({"type": "http", "method": "GET", "path": "/"})

        result = await provider.complete_authorization(request)

        self.assertEqual(result.claim_names, ("aud", "iss", "sub"))
        self.assertEqual(
            result.userinfo_claim_names,
            ("email_verified", "name", "sub"),
        )
        self.assertFalse(result.userinfo_subject_matches)

    async def test_id_token_is_required(self) -> None:
        provider = self.provider()
        client = FakeOidcClient()

        async def authorize_without_id_token(
            request: Request,
        ) -> dict[str, Any]:
            del request
            return {"access_token": "test-access-token"}

        client.authorize_access_token = authorize_without_id_token  # type: ignore[method-assign]
        provider._client = client  # type: ignore[assignment]
        request = Request({"type": "http", "method": "GET", "path": "/"})

        with self.assertRaises(OidcAuthenticationError):
            await provider.complete_authorization(request)


class OidcTokenResponseCompatibilityTest(unittest.TestCase):
    def test_unwraps_successful_nested_token_response(self) -> None:
        request = httpx.Request("POST", "https://issuer.example/token")
        response = httpx.Response(
            200,
            request=request,
            json={
                "error": None,
                "data": {
                    "access_token": "access-token",
                    "id_token": "id-token",
                },
            },
        )

        normalized = _normalize_token_response(response)

        self.assertEqual(
            normalized.json(),
            {"access_token": "access-token", "id_token": "id-token"},
        )

    def test_does_not_unwrap_response_with_outer_error(self) -> None:
        request = httpx.Request("POST", "https://issuer.example/token")
        response = httpx.Response(
            200,
            request=request,
            json={
                "error": "invalid_grant",
                "data": {"access_token": "untrusted-token"},
            },
        )

        self.assertIs(_normalize_token_response(response), response)


if __name__ == "__main__":
    unittest.main()
