from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Annotated

import httpx
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Request
from starlette.types import ASGIApp

from backend.app.core.auth import require_completed_profile, require_teacher
from backend.app.core.config import Settings
from backend.app.db.models.user import User
from backend.app.factory import create_app
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
    ExternalIdentity,
    IdentityProviderCapabilities,
    LoginMethod,
    OidcAuthorizationResult,
    OidcIdentityProvider,
    PlaceholderIdentityProvider,
)
from backend.app.repositories.users import UserRepository
from backend.app.services.users import UserService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RedirectIdentityProvider:
    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        del request
        return None

    def capabilities(self) -> IdentityProviderCapabilities:
        return IdentityProviderCapabilities(
            login_method=LoginMethod.REDIRECT,
            login_url="/auth/oidc/login",
        )

    async def end_session(self, request: Request) -> str | None:
        del request
        return "https://issuer.example/logout"


class AuthenticationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        self.database_url = f"sqlite:///{self.root / 'auth.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", self.database_url)
        command.upgrade(config, "head")

    def tearDown(self) -> None:
        self.temporary_dir.cleanup()

    def settings(self, *, debug_auth_enabled: bool) -> Settings:
        return Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=debug_auth_enabled,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=self.database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )

    @staticmethod
    def add_protected_routes(app: FastAPI) -> None:
        @app.get("/test/teacher")
        async def teacher(
            user: Annotated[User, Depends(require_teacher)],
        ) -> dict[str, object]:
            return {"id": user.id, "userId": user.user_id}

        @app.get("/test/completed")
        async def completed(
            user: Annotated[User, Depends(require_completed_profile)],
        ) -> dict[str, object]:
            return {"id": user.id, "userId": user.user_id}

    @staticmethod
    async def request(
        app: ASGIApp,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    @staticmethod
    def debug_headers(subject: str) -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: subject,
        }

    def test_anonymous_pending_and_completed_permissions(self) -> None:
        app = create_app(self.settings(debug_auth_enabled=True))
        self.add_protected_routes(app)

        anonymous = asyncio.run(self.request(app, "GET", "/test/teacher"))
        pending_teacher = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/teacher",
                headers=self.debug_headers("pending"),
            )
        )
        pending_completed = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/completed",
                headers=self.debug_headers("pending"),
            )
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(pending_teacher.status_code, 200)
        self.assertEqual(pending_completed.status_code, 403)

        session_factory = app.state.session_factory
        with session_factory() as session:
            user = UserRepository().get_by_identity(
                session, "https://issuer.example", "pending"
            )
            assert user is not None
            UserService().set_user_id(session, user, "PendingTeacher")
            session.commit()

        completed_teacher = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/completed",
                headers=self.debug_headers("pending"),
            )
        )
        self.assertEqual(completed_teacher.status_code, 200)
        self.assertEqual(completed_teacher.json()["userId"], "PendingTeacher")

    def test_signed_placeholder_session_authenticates_same_identity(self) -> None:
        async def scenario(app: ASGIApp) -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                login = await client.post(
                    "/auth/debug/session",
                    json={
                        "issuer": "https://issuer.example",
                        "subject": "session-teacher",
                    },
                )
                protected = await client.get("/test/teacher")
                return login, protected

        app = create_app(self.settings(debug_auth_enabled=True))
        self.add_protected_routes(app)
        login, protected = asyncio.run(scenario(app))

        self.assertEqual(login.status_code, 204)
        self.assertIn("HttpOnly", login.headers["set-cookie"])
        self.assertEqual(protected.status_code, 200)
        self.assertEqual(protected.json()["id"], 1)

    def test_authentication_capabilities_and_provider_logout_boundary(self) -> None:
        debug_app = create_app(self.settings(debug_auth_enabled=True))
        disabled_app = create_app(self.settings(debug_auth_enabled=False))
        redirect_app = create_app(
            self.settings(debug_auth_enabled=False),
            identity_provider=RedirectIdentityProvider(),
        )

        debug = asyncio.run(self.request(debug_app, "GET", "/auth/capabilities"))
        disabled = asyncio.run(
            self.request(disabled_app, "GET", "/auth/capabilities")
        )
        redirect = asyncio.run(
            self.request(redirect_app, "GET", "/auth/capabilities")
        )
        logout = asyncio.run(
            self.request(redirect_app, "DELETE", "/auth/session")
        )

        self.assertEqual(debug.json(), {"loginMethod": "debug", "loginUrl": None})
        self.assertEqual(disabled.json(), {"loginMethod": "none", "loginUrl": None})
        self.assertEqual(
            redirect.json(),
            {"loginMethod": "redirect", "loginUrl": "/auth/oidc/login"},
        )
        self.assertEqual(
            logout.json(),
            {"redirectUrl": "https://issuer.example/logout"},
        )

        debug_app.state.db_engine.dispose()
        disabled_app.state.db_engine.dispose()
        redirect_app.state.db_engine.dispose()

    def test_spoofed_database_and_user_ids_do_not_select_identity(self) -> None:
        app = create_app(self.settings(debug_auth_enabled=True))
        self.add_protected_routes(app)
        forged_headers = {
            "X-User-ID": "1",
            "X-UserId": "AnotherTeacher",
        }

        forged_only = asyncio.run(
            self.request(app, "GET", "/test/teacher", headers=forged_headers)
        )
        actual_identity = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/teacher",
                headers={**forged_headers, **self.debug_headers("actual")},
            )
        )

        self.assertEqual(forged_only.status_code, 401)
        self.assertEqual(actual_identity.status_code, 200)
        self.assertIsNone(actual_identity.json()["userId"])

    def test_debug_headers_and_session_are_ignored_when_disabled(self) -> None:
        enabled_settings = self.settings(debug_auth_enabled=True)
        token = PlaceholderIdentityProvider(enabled_settings).issue_session(
            ExternalIdentity("https://issuer.example", "disabled")
        )
        disabled_settings = self.settings(debug_auth_enabled=False)
        app = create_app(disabled_settings)
        self.add_protected_routes(app)

        header_response = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/teacher",
                headers=self.debug_headers("disabled"),
            )
        )
        cookie_response = asyncio.run(
            self.request(
                app,
                "GET",
                "/test/teacher",
                headers={
                    "Cookie": (
                        f"{disabled_settings.auth_session_cookie_name}={token}"
                    )
                },
            )
        )
        debug_entry = asyncio.run(
            self.request(
                app,
                "POST",
                "/auth/debug/session",
                headers=self.debug_headers("disabled"),
            )
        )

        self.assertEqual(header_response.status_code, 401)
        self.assertEqual(cookie_response.status_code, 401)
        self.assertEqual(debug_entry.status_code, 404)

    def test_oidc_callback_creates_application_session(self) -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=False,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=self.database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
            oidc_enabled=True,
            oidc_discovery_url=(
                "https://issuer.example/.well-known/openid-configuration"
            ),
            oidc_client_id="client-id",
            oidc_client_secret="client-secret",
            oidc_redirect_uri="http://testserver/auth/oidc/callback",
            oidc_post_login_url="http://frontend.test/",
        )
        app = create_app(settings)
        provider = app.state.identity_provider
        assert isinstance(provider, OidcIdentityProvider)

        async def complete_authorization(
            request: Request,
        ) -> OidcAuthorizationResult:
            self.assertIsInstance(request.session, dict)
            return OidcAuthorizationResult(
                identity=ExternalIdentity(
                    "https://issuer.example",
                    "oidc-user",
                    suggested_username="Teacher One",
                ),
                claim_names=("iss", "name", "sub"),
            )

        provider.complete_authorization = complete_authorization  # type: ignore[method-assign]

        async def scenario() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                callback = await client.get("/auth/oidc/callback")
                current_user = await client.get("/api/users/me")
                return callback, current_user

        callback, current_user = asyncio.run(scenario())

        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers["location"], "http://frontend.test/")
        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(current_user.json()["userId"], None)
        self.assertEqual(current_user.json()["suggestedUsername"], "Teacher One")
        self.assertFalse(current_user.json()["profileComplete"])
        app.state.db_engine.dispose()


if __name__ == "__main__":
    unittest.main()
