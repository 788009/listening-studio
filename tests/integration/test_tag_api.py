from __future__ import annotations

import asyncio
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.voice import VoiceStatus, VoiceVisibility
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
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
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

    @staticmethod
    def write_wav(path: Path) -> None:
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 800)

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

    def test_request_locale_priority_fallback_and_validation(self) -> None:
        self.complete_profile()
        created = self.send(
            "POST",
            "/api/audio-tags",
            headers=self.headers(),
            json={
                "type": "topic",
                "value": "Climate Change",
                "translations": [{"language": "zh-CN", "value": "气候 变化"}],
            },
        )
        fallback = self.create_audio_tag("No Translation")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(fallback.status_code, 201)

        anonymous_chinese = self.send(
            "GET",
            "/api/audio-tags?type=topic",
            headers={"Accept-Language": "zh-CN, en;q=0.5"},
        )
        self.assertEqual(anonymous_chinese.status_code, 200)
        values = {item["englishValue"]: item for item in anonymous_chinese.json()}
        self.assertEqual(values["Climate_Change"]["displayValue"], "气候 变化")
        self.assertEqual(
            values["No_Translation"]["displayValue"],
            "No Translation",
        )
        self.assertEqual(
            values["Climate_Change"]["fullTag"],
            "topic:Climate_Change",
        )

        updated = self.send(
            "PATCH",
            "/api/users/me/profile",
            headers=self.headers(),
            json={"locale": "zh-CN"},
        )
        self.assertEqual(updated.status_code, 200)
        user_preference = self.send(
            "GET",
            f"/api/audio-tags/{created.json()['id']}",
            headers={**self.headers(), "Accept-Language": "en"},
        )
        explicit_english = self.send(
            "GET",
            f"/api/audio-tags/{created.json()['id']}?language=en",
            headers={**self.headers(), "Accept-Language": "zh-CN"},
        )
        unsupported = self.send("GET", "/api/audio-tags?language=fr")
        localized_error = self.send(
            "GET",
            "/api/audio-tags/99999",
            headers={"Accept-Language": "zh-CN"},
        )

        self.assertEqual(user_preference.json()["displayValue"], "气候 变化")
        self.assertEqual(explicit_english.json()["displayValue"], "Climate Change")
        self.assertEqual(unsupported.status_code, 422)
        self.assertEqual(localized_error.status_code, 404)
        self.assertEqual(localized_error.json()["error"]["code"], "not_found")
        self.assertEqual(localized_error.json()["error"]["message"], "未找到资源")

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
        second_audio = self.create_audio_tag("Teacher", tag_type="voice")
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

    def test_autocomplete_translation_alias_order_domain_and_limit(self) -> None:
        self.complete_profile()
        climate = self.send(
            "POST",
            "/api/audio-tags",
            headers=self.headers(),
            json={
                "type": "topic",
                "value": "Climate Change",
                "translations": [{"language": "zh-CN", "value": "气候 变化"}],
            },
        )
        self.create_audio_tag("Climate Policy", tag_type="category")
        self.create_audio_tag("Tropical Climate")
        self.create_audio_tag("Anzu", tag_type="voice")
        self.create_voice_tag("Female Voice")
        self.assertEqual(climate.status_code, 201)

        translated = self.send("GET", "/api/audio-tags/autocomplete?q=气候")
        abbreviated = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=t:climate",
        )
        ordered = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=climate&limit=2",
        )
        voice_alias = self.send(
            "GET",
            "/api/voice-tags/autocomplete?q=g:fem",
        )
        audio_voice_alias = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=v:anz",
        )
        old_speaker_alias = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=s:anz",
        )
        cross_domain = self.send(
            "GET",
            "/api/voice-tags/autocomplete?q=topic:climate",
        )
        excessive_limit = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=climate&limit=21",
        )

        self.assertEqual(translated.json(), ["topic:climate_change"])
        self.assertEqual(
            abbreviated.json(),
            ["topic:climate_change", "topic:tropical_climate"],
        )
        self.assertEqual(
            ordered.json(),
            ["category:climate_policy", "topic:climate_change"],
        )
        self.assertEqual(voice_alias.json(), ["gender:female_voice"])
        self.assertEqual(audio_voice_alias.json(), ["voice:anzu"])
        self.assertEqual(old_speaker_alias.status_code, 422)
        self.assertEqual(cross_domain.status_code, 422)
        self.assertEqual(excessive_limit.status_code, 422)

    def test_author_autocomplete_obeys_resource_visibility(self) -> None:
        self.complete_profile("TeacherOne")
        other_profile = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers("other"),
            json={"userId": "TeacherTwo", "username": "Other Teacher"},
        )
        self.assertEqual(other_profile.status_code, 200)

        voice_storage = VoiceStorage(self.settings.data_dir)
        audio_storage = AudioStorage(self.settings.data_dir)
        voice_service = VoiceService(voice_storage)
        audio_service = AudioService(audio_storage)
        with self.app.state.session_factory() as session:
            first = UserRepository().get_by_user_id(session, "TeacherOne")
            second = UserRepository().get_by_user_id(session, "TeacherTwo")
            assert first is not None and second is not None
            voice_service.create_voice(
                session,
                author=first,
                title="Private first voice",
            )
            first_audio = audio_service.create_audio(
                session,
                author=first,
                title="Private first audio",
                source_type=AudioSourceType.CORPUS,
                text="Private first text",
            )
            second_voice = voice_service.create_voice(
                session,
                author=second,
                title="Public second voice",
            )
            second_audio = audio_service.create_audio(
                session,
                author=second,
                title="Public second audio",
                source_type=AudioSourceType.CORPUS,
                text="Public second text",
            )

            voice_service.transition_status(
                session,
                second_voice,
                VoiceStatus.PROCESSING,
            )
            model_temporary = voice_storage.create_temporary_file(
                second_voice.id,
                VoiceAsset.MODEL,
            )
            model_temporary.write_bytes(b"model")
            voice_storage.atomic_replace(
                second_voice.id,
                VoiceAsset.MODEL,
                model_temporary,
            )
            voice_service.transition_status(
                session,
                second_voice,
                VoiceStatus.READY,
            )
            voice_service.set_visibility(
                session,
                second_voice,
                VoiceVisibility.PUBLIC,
            )

            audio_service.transition_status(
                session,
                second_audio,
                AudioStatus.PROCESSING,
            )
            output = audio_storage.temporary_audio_path(second_audio.id)
            self.write_wav(output)
            audio_storage.atomic_replace(second_audio.id, second_audio.id)
            audio_service.record_file_metadata(session, second_audio)
            audio_service.transition_status(
                session,
                second_audio,
                AudioStatus.READY,
            )
            audio_service.set_visibility(
                session,
                second_audio,
                AudioVisibility.PUBLIC,
            )
            session.commit()
            self.assertEqual(first_audio.visibility, AudioVisibility.PRIVATE)

        owner_voice = self.send(
            "GET",
            "/api/voice-tags/autocomplete?q=a:",
            headers=self.headers(),
        )
        owner_audio = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=author:",
            headers=self.headers(),
        )
        anonymous_voice = self.send(
            "GET",
            "/api/voice-tags/autocomplete?q=author:",
        )
        anonymous_audio = self.send(
            "GET",
            "/api/audio-tags/autocomplete?q=author:",
        )

        expected_teacher_results = ["author:teacherone", "author:teachertwo"]
        self.assertEqual(owner_voice.json(), expected_teacher_results)
        self.assertEqual(owner_audio.json(), expected_teacher_results)
        self.assertEqual(anonymous_voice.json(), [])
        self.assertEqual(anonymous_audio.json(), ["author:teachertwo"])


if __name__ == "__main__":
    unittest.main()
