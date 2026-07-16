from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Annotated

import httpx
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from starlette.types import ASGIApp

from backend.app.core.auth import require_completed_profile, require_teacher
from backend.app.core.config import Settings
from backend.app.db.models.user import User
from backend.app.factory import create_app
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
    ExternalIdentity,
    PlaceholderIdentityProvider,
)
from backend.app.repositories.users import UserRepository
from backend.app.services.users import UserService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
                    headers=self.debug_headers("session-teacher"),
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


if __name__ == "__main__":
    unittest.main()
