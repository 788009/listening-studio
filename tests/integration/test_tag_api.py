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
from backend.app.db.models.audio import AudioSourceType
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.factory import create_app
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
)
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.users import UserRepository
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TagApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'tag-api.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )
        self.app = create_app(settings)
        self.settings = settings

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers(subject: str = "teacher") -> dict[str, str]:
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
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def complete_profile(self, user_id: str = "TagTeacher") -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(),
            json={"userId": user_id, "username": "Tag Teacher"},
        )
        self.assertEqual(response.status_code, 200)

    def create_voice_tag(
        self,
        value: str,
        *,
        tag_type: str = "gender",
    ) -> httpx.Response:
        return self.send(
            "POST",
            "/api/voice-tags",
            headers=self.headers(),
            json={"type": tag_type, "value": value},
        )

    def create_audio_tag(
        self,
        value: str,
        *,
        tag_type: str = "topic",
    ) -> httpx.Response:
        return self.send(
            "POST",
            "/api/audio-tags",
            headers=self.headers(),
            json={"type": tag_type, "value": value},
        )

    def test_voice_tag_create_query_and_translation_upsert(self) -> None:
        self.complete_profile()
        created = self.send(
            "POST",
            "/api/voice-tags?language=zh-CN",
            headers=self.headers(),
            json={
                "type": "gender",
                "value": "Female Voice",
                "translations": [{"language": "zh_cn", "value": "女性 声音"}],
            },
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["englishValue"], "Female_Voice")
        self.assertEqual(created.json()["displayValue"], "女性 声音")
        self.assertEqual(created.json()["fullTag"], "gender:Female_Voice")

        listed = self.send(
            "GET",
            "/api/voice-tags?type=gender&language=zh-CN",
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["displayValue"], "女性 声音")

        tag_id = created.json()["id"]
        added = self.send(
            "PUT",
            f"/api/voice-tags/{tag_id}/translations/fr",
            headers=self.headers(),
            json={"value": "Voix Femme"},
        )
        updated = self.send(
            "PUT",
            f"/api/voice-tags/{tag_id}/translations/fr",
            headers=self.headers(),
            json={"value": "Voix Féminine"},
        )

        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json()["displayValue"], "Voix Femme")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["displayValue"], "Voix Féminine")
        self.assertEqual(len(updated.json()["translations"]), 2)

    def test_domains_types_author_and_permissions_are_isolated(self) -> None:
        anonymous = self.send(
            "POST",
            "/api/voice-tags",
            json={"type": "gender", "value": "Female"},
        )
        self.assertEqual(anonymous.status_code, 401)
        self.complete_profile()

        voice = self.create_voice_tag("Female")
        first_audio = self.create_audio_tag("Climate")
        second_audio = self.create_audio_tag("Teacher", tag_type="speaker")
        wrong_voice_type = self.create_voice_tag("Climate", tag_type="topic")
        wrong_audio_type = self.create_audio_tag("Female", tag_type="gender")
        voice_author = self.create_voice_tag("TagTeacher", tag_type="author")
        audio_author = self.create_audio_tag("TagTeacher", tag_type="author")

        self.assertEqual(voice.status_code, 201)
        self.assertEqual(first_audio.status_code, 201)
        self.assertEqual(second_audio.status_code, 201)
        for response in (
            wrong_voice_type,
            wrong_audio_type,
            voice_author,
            audio_author,
        ):
            self.assertEqual(response.status_code, 422)

        audio_only_id = second_audio.json()["id"]
        wrong_domain = self.send("GET", f"/api/voice-tags/{audio_only_id}")
        correct_domain = self.send("GET", f"/api/audio-tags/{audio_only_id}")
        self.assertEqual(wrong_domain.status_code, 404)
        self.assertEqual(correct_domain.status_code, 200)

    def test_delete_rejects_author_and_linked_tags_with_usage_count(self) -> None:
        self.complete_profile()
        voice_tag_response = self.create_voice_tag("Female")
        audio_tag_response = self.create_audio_tag("Climate")
        unused_response = self.create_audio_tag("Unused", tag_type="category")

        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, "TagTeacher")
            assert user is not None
            voice_tag = VoiceTagRepository().get_by_id(
                session,
                voice_tag_response.json()["id"],
            )
            audio_tag = AudioTagRepository().get_by_id(
                session,
                audio_tag_response.json()["id"],
            )
            assert voice_tag is not None and audio_tag is not None
            voice = VoiceService(VoiceStorage(self.settings.data_dir)).create_voice(
                session,
                author=user,
                title="Tagged voice",
            )
            voice.tags.append(voice_tag)
            AudioService(AudioStorage(self.settings.data_dir)).create_audio(
                session,
                author=user,
                title="Tagged audio",
                source_type=AudioSourceType.CORPUS,
                text="Tagged text",
                tags=[audio_tag],
            )
            session.commit()

        voice_conflict = self.send(
            "DELETE",
            f"/api/voice-tags/{voice_tag_response.json()['id']}",
            headers=self.headers(),
        )
        audio_conflict = self.send(
            "DELETE",
            f"/api/audio-tags/{audio_tag_response.json()['id']}",
            headers=self.headers(),
        )
        deleted = self.send(
            "DELETE",
            f"/api/audio-tags/{unused_response.json()['id']}",
            headers=self.headers(),
        )

        self.assertEqual(voice_conflict.status_code, 409)
        self.assertEqual(
            voice_conflict.json()["error"]["details"]["usageCount"],
            1,
        )
        self.assertEqual(audio_conflict.status_code, 409)
        self.assertEqual(
            audio_conflict.json()["error"]["details"]["usageCount"],
            1,
        )
        self.assertEqual(deleted.status_code, 204)

        voice_tags = self.send("GET", "/api/voice-tags").json()
        author_tag = next(tag for tag in voice_tags if tag["type"] == "author")
        protected = self.send(
            "DELETE",
            f"/api/voice-tags/{author_tag['id']}",
            headers=self.headers(),
        )
        self.assertEqual(protected.status_code, 409)

    def test_concurrent_normalized_create_has_one_recoverable_conflict(self) -> None:
        self.complete_profile()

        async def create_concurrently() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return list(
                    await asyncio.gather(
                        client.post(
                            "/api/audio-tags",
                            headers=self.headers(),
                            json={"type": "topic", "value": "Climate Change"},
                        ),
                        client.post(
                            "/api/audio-tags",
                            headers=self.headers(),
                            json={"type": "topic", "value": "climate   change"},
                        ),
                    )
                )

        responses = asyncio.run(create_concurrently())
        self.assertEqual(sorted(response.status_code for response in responses), [
            201,
            409,
        ])
        conflict = next(
            response for response in responses if response.status_code == 409
        )
        self.assertEqual(conflict.json()["error"]["code"], "conflict")


if __name__ == "__main__":
    unittest.main()
