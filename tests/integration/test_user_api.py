from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from backend.app.core.config import Settings
from backend.app.factory import create_app
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UserApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{root / 'users-api.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=root / "model",
            database_url=database_url,
            data_dir=root / "data",
            log_dir=root / "logs",
        )
        self.app = create_app(settings)

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers(subject: str) -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: subject,
        }

    @staticmethod
    async def request(
        app: FastAPI,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def complete_profile(
        self,
        subject: str,
        user_id: str,
        *,
        username: str = "Teacher",
    ) -> httpx.Response:
        return self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": username, "locale": "en"},
        )

    def test_profile_setup_validation_uniqueness_and_immutability(self) -> None:
        invalid = self.complete_profile("first", "invalid-id")
        created = self.complete_profile("first", "TeacherOne")
        duplicate = self.send(
            "POST",
            "/api/users/me/profile",
            headers={**self.headers("second"), "Accept-Language": "zh-CN"},
            json={
                "userId": "teacherone",
                "username": "Teacher",
                "locale": "zh-CN",
            },
        )
        changed = self.complete_profile("first", "AnotherId")
        public_route = self.send("GET", "/api/users/teacherone")

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["userId"], "TeacherOne")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "user_id_taken")
        self.assertEqual(duplicate.json()["error"]["details"], {"field": "userId"})
        self.assertEqual(
            duplicate.json()["error"]["message"],
            "该用户 ID 已被占用，请选择其他 ID",
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "user_id_immutable")
        self.assertEqual(changed.json()["error"]["details"], {"field": "userId"})
        self.assertEqual(
            changed.json()["error"]["message"],
            "User ID has already been set and cannot be changed.",
        )
        self.assertEqual(public_route.status_code, 200)
        self.assertEqual(public_route.json()["userId"], "TeacherOne")

    def test_initial_and_updated_locale_use_supported_values(self) -> None:
        pending = self.send(
            "GET",
            "/api/users/me",
            headers={
                **self.headers("localized"),
                "Accept-Language": "zh-CN, en;q=0.5",
            },
        )
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["locale"], "zh-CN")

        completed = self.complete_profile("localized", "LocalizedTeacher")
        unsupported = self.send(
            "PATCH",
            "/api/users/me/profile",
            headers=self.headers("localized"),
            json={"locale": "fr"},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(unsupported.status_code, 422)
        self.assertEqual(unsupported.json()["error"]["code"], "validation_error")

    def test_profile_update_keeps_user_route_and_identity(self) -> None:
        self.complete_profile("first", "StableRoute", username="Initial Name")
        before = self.send("GET", "/api/users/stableroute")
        updated = self.send(
            "PATCH",
            "/api/users/me/profile",
            headers=self.headers("first"),
            json={"username": "Updated Name", "locale": "zh_cn"},
        )
        after = self.send("GET", "/api/users/StableRoute")

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["username"], "Updated Name")
        self.assertEqual(updated.json()["locale"], "zh-CN")
        self.assertEqual(before.json()["userId"], after.json()["userId"])
        self.assertEqual(after.json()["username"], "Updated Name")

    def test_private_statistics_are_returned_only_to_same_user(self) -> None:
        self.complete_profile("first", "StatsTeacher")
        anonymous = self.send("GET", "/api/users/StatsTeacher")
        owner = self.send(
            "GET",
            "/api/users/StatsTeacher",
            headers=self.headers("first"),
        )

        self.assertNotIn("privateStatistics", anonymous.json())
        self.assertEqual(
            owner.json()["privateStatistics"],
            {"privateVoiceCount": 0, "privateAudioCount": 0},
        )

    def test_pending_teacher_update_has_specialized_error(self) -> None:
        response = self.send(
            "PATCH",
            "/api/users/me/profile",
            headers=self.headers("pending"),
            json={"username": "Pending Teacher"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "profile_incomplete")


if __name__ == "__main__":
    unittest.main()
