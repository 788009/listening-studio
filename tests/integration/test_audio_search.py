from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.user import User
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_management import AudioManagementService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audios import AudioService
from backend.app.services.tag_values import TagTranslationInput


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioSearchIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'audio-search.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )
        self.app = create_app(self.settings)
        self.storage = AudioStorage(self.settings.data_dir)
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")

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
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def complete_profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def user(session: Session, user_id: str) -> User:
        user = UserRepository().get_by_user_id(session, user_id)
        assert user is not None
        return user

    def audio(
        self,
        session: Session,
        author: User,
        title: str,
        *,
        tags: list[AudioTag] | None = None,
        visibility: AudioVisibility = AudioVisibility.PUBLIC,
        status: AudioStatus = AudioStatus.READY,
        with_file: bool = True,
        text: str = "Body text is not searchable",
    ) -> Audio:
        audio = AudioService(self.storage).create_audio(
            session,
            author=author,
            title=title,
            source_type=AudioSourceType.CORPUS,
            text=text,
            tags=tags or [],
        )
        audio.status = status
        audio.visibility = visibility
        if with_file:
            self.storage.prepare_directory(audio.id)
            self.storage.path(audio.id).write_bytes(b"search-test-audio")
        return audio

    def test_combined_title_tag_translation_and_literal_search(self) -> None:
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            tags = AudioTagService()
            topic = tags.create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="Climate Change",
                translations=[TagTranslationInput("zh-CN", "气候 变化")],
            )
            teacher = tags.create_user_tag(
                session,
                tag_type=AudioTagType.SPEAKER,
                english_value="Teacher",
                translations=[TagTranslationInput("fr", "Professeur")],
            )
            scientist = tags.create_user_tag(
                session,
                tag_type=AudioTagType.SPEAKER,
                english_value="Scientist",
            )
            news = tags.create_user_tag(
                session,
                tag_type=AudioTagType.CATEGORY,
                english_value="News",
            )
            target = self.audio(
                session,
                first,
                "Ａrctic 100%_Report\\Draft",
                tags=[topic, teacher, scientist, news],
                text="exclusive_body_phrase",
            )
            self.audio(session, first, "Ocean current", tags=[topic])
            session.commit()

        cases = (
            ("ARCTIC t:气候_变化 s:teacher", [target.id]),
            ("arctic professeur", [target.id]),
            ("s:scientist topic:climate_change", [target.id]),
            ("c:news", [target.id]),
            (r"100%_report\draft", [target.id]),
            ("exclusive_body_phrase", []),
            ("topic:no_result", []),
        )
        for query, expected_ids in cases:
            with self.subTest(query=query):
                response = self.send("GET", "/api/audios", params={"q": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["id"] for item in response.json()["items"]],
                    expected_ids,
                )

        captured: list[tuple[str, object]] = []

        def capture_sql(
            connection: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            del connection, cursor, context, executemany
            if "normalized_title LIKE" in statement:
                captured.append((statement, parameters))

        event.listen(self.app.state.db_engine, "before_cursor_execute", capture_sql)
        try:
            response = self.send(
                "GET",
                "/api/audios",
                params={"q": r"100%_report\draft"},
            )
        finally:
            event.remove(
                self.app.state.db_engine,
                "before_cursor_execute",
                capture_sql,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured)
        statement, parameters = captured[0]
        self.assertNotIn("100%_report", statement)
        self.assertIn(r"%100\%\_report\\draft%", parameters)

    def test_visibility_total_and_pagination_do_not_leak(self) -> None:
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            second = self.user(session, "TeacherTwo")
            public_first = self.audio(session, first, "Shared search")
            public_second = self.audio(session, second, "Shared search")
            own_private = self.audio(
                session,
                first,
                "Owner secret search",
                visibility=AudioVisibility.PRIVATE,
            )
            self.audio(
                session,
                second,
                "Hidden secret search",
                visibility=AudioVisibility.PRIVATE,
            )
            self.audio(
                session,
                second,
                "Shared search missing",
                with_file=False,
            )
            self.audio(
                session,
                second,
                "Shared search failed",
                status=AudioStatus.FAILED,
            )
            session.commit()

        anonymous_page_one = self.send(
            "GET",
            "/api/audios",
            params={"q": "shared", "page": 1, "page_size": 1},
        )
        anonymous_page_two = self.send(
            "GET",
            "/api/audios",
            params={"q": "shared", "page": 2, "page_size": 1},
        )
        owner_private = self.send(
            "GET",
            "/api/audios",
            headers=self.headers("first"),
            params={"q": "owner secret"},
        )
        hidden_private = self.send(
            "GET",
            "/api/audios",
            headers=self.headers("first"),
            params={"q": "hidden secret"},
        )

        self.assertEqual(anonymous_page_one.json()["total"], 2)
        self.assertEqual(anonymous_page_two.json()["total"], 2)
        self.assertEqual(
            [anonymous_page_one.json()["items"][0]["id"]],
            [public_second.id],
        )
        self.assertEqual(
            [anonymous_page_two.json()["items"][0]["id"]],
            [public_first.id],
        )
        self.assertEqual(
            [item["id"] for item in owner_private.json()["items"]],
            [own_private.id],
        )
        self.assertEqual(hidden_private.json()["total"], 0)

    def test_basic_search_performance(self) -> None:
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            service = AudioService(self.storage)
            for index in range(200):
                service.create_audio(
                    session,
                    author=first,
                    title=f"Benchmark search {index:03d}",
                    source_type=AudioSourceType.CORPUS,
                    text="Not searched",
                )
            session.commit()

        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            started_at = time.perf_counter()
            result = AudioManagementService(self.storage).list_visible(
                session,
                Principal(first),
                page=1,
                page_size=100,
                query="benchmark search",
            )
            elapsed = time.perf_counter() - started_at

        self.assertEqual(result.total, 200)
        self.assertEqual(len(result.items), 100)
        self.assertLess(elapsed, 1.5)


if __name__ == "__main__":
    unittest.main()
