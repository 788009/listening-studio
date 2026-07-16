from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.user import User
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
)
from backend.app.repositories.users import UserRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService, AudioUtteranceInput
from backend.app.services.voice_management import VoiceManagementService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voice_tags import VoiceTagService
from backend.app.services.voice_uploads import VoiceUploadService
from backend.app.services.voices import VoiceService
from backend.app.services.tag_values import TagTranslationInput


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VoiceApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'voice-api.sqlite3'}"
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
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)

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
            transport=transport,
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
    def wav_bytes() -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 16000)
        return output.getvalue()

    def user(self, session: Session, user_id: str) -> User:
        user = UserRepository().get_by_user_id(session, user_id)
        assert user is not None
        return user

    def upload_voice(
        self,
        session: Session,
        author: User,
        title: str,
        visibility: VoiceVisibility,
        gender_tag_id: int | None = None,
    ) -> Voice:
        return VoiceUploadService(
            integration=FakeCosyVoiceIntegration(),
            storage=self.voice_storage,
            max_upload_bytes=1024 * 1024,
        ).create_from_upload(
            session,
            author=author,
            title=title,
            filename="reference.wav",
            content=self.wav_bytes(),
            gender_tag_id=gender_tag_id,
            target_visibility=visibility,
            request_id="voice-api-setup",
        )

    def ready_audio(
        self,
        session: Session,
        author: User,
        title: str,
        visibility: AudioVisibility,
    ) -> Audio:
        service = AudioService(self.audio_storage)
        audio = service.create_audio(
            session,
            author=author,
            title=title,
            source_type=AudioSourceType.CORPUS,
            text="Sample text",
        )
        service.transition_status(session, audio, AudioStatus.PROCESSING)
        voice_file = self.root / f"audio-voice-{audio.id}.pt"
        voice_file.write_bytes(b"voice")
        temporary = self.audio_storage.temporary_audio_path(audio.id)
        FakeCosyVoiceIntegration().synthesize(voice_file, "text", temporary)
        self.audio_storage.atomic_replace(audio.id, audio.id)
        service.record_file_metadata(session, audio)
        service.transition_status(session, audio, AudioStatus.READY)
        service.set_visibility(session, audio, visibility)
        return audio

    def test_list_detail_filters_search_and_permissions(self) -> None:
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            second = self.user(session, "TeacherTwo")
            female = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="Female Voice",
                translations=[],
            )
            VoiceTagService().upsert_translation(
                session,
                tag_id=female.id,
                translation=self._translation("zh-CN", "女性 声音"),
            )
            own_private = self.upload_voice(
                session,
                first,
                "100%_Literal\\Title",
                VoiceVisibility.PRIVATE,
                female.id,
            )
            own_public = self.upload_voice(
                session,
                first,
                "Public climate",
                VoiceVisibility.PUBLIC,
                female.id,
            )
            other_private = self.upload_voice(
                session,
                second,
                "Hidden voice",
                VoiceVisibility.PRIVATE,
            )
            other_public = self.upload_voice(
                session,
                second,
                "Shared voice",
                VoiceVisibility.PUBLIC,
            )

        anonymous = self.send("GET", "/api/voices")
        owner = self.send("GET", "/api/voices", headers=self.headers("first"))
        other = self.send("GET", "/api/voices", headers=self.headers("second"))
        translated = self.send(
            "GET",
            "/api/voices",
            headers=self.headers("first"),
            params={"q": "g:女性_声音", "language": "zh-CN"},
        )
        literal = self.send(
            "GET",
            "/api/voices",
            headers=self.headers("first"),
            params={"q": "%_literal\\"},
        )
        filtered = self.send(
            "GET",
            "/api/voices",
            headers=self.headers("first"),
            params={"author": "TeacherTwo", "visibility": "public"},
        )
        paged = self.send(
            "GET",
            "/api/voices?page=1&page_size=1",
            headers=self.headers("first"),
        )

        self.assertEqual(anonymous.json()["total"], 0)
        self.assertEqual(
            {item["id"] for item in owner.json()["items"]},
            {own_private.id, own_public.id, other_public.id},
        )
        self.assertEqual(
            {item["id"] for item in other.json()["items"]},
            {own_public.id, other_private.id, other_public.id},
        )
        self.assertEqual(translated.json()["total"], 2)
        translated_tags = translated.json()["items"][0]["tags"]
        self.assertEqual(
            next(tag for tag in translated_tags if tag["type"] == "gender")[
                "displayValue"
            ],
            "女性 声音",
        )
        self.assertEqual([item["id"] for item in literal.json()["items"]], [
            own_private.id
        ])
        self.assertEqual(
            [item["id"] for item in filtered.json()["items"]],
            [other_public.id],
        )
        self.assertEqual(paged.json()["pageSize"], 1)
        self.assertEqual(len(paged.json()["items"]), 1)
        hidden = self.send(
            "GET",
            f"/api/voices/{other_private.id}",
            headers=self.headers("first"),
        )
        self.assertEqual(hidden.status_code, 404)

    def test_owner_update_preserves_author_and_enforces_publish_rules(self) -> None:
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            male = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="Male",
            )
            female = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="Female",
            )
            ready = self.upload_voice(
                session,
                first,
                "Before",
                VoiceVisibility.PRIVATE,
                male.id,
            )
            pending = VoiceService(self.voice_storage).create_voice(
                session,
                author=first,
                title="Pending",
            )
            session.commit()

        updated = self.send(
            "PATCH",
            f"/api/voices/{ready.id}",
            headers=self.headers("first"),
            json={
                "title": "Ａfter",
                "genderTagIds": [female.id],
                "visibility": "public",
            },
        )
        forbidden = self.send(
            "PATCH",
            f"/api/voices/{ready.id}",
            headers=self.headers("second"),
            json={"title": "Other"},
        )
        unavailable = self.send(
            "PATCH",
            f"/api/voices/{pending.id}",
            headers=self.headers("first"),
            json={"visibility": "public"},
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "After")
        self.assertEqual(updated.json()["visibility"], "public")
        self.assertEqual(
            {tag["type"] for tag in updated.json()["tags"]},
            {"author", "gender"},
        )
        self.assertEqual(
            next(tag for tag in updated.json()["tags"] if tag["type"] == "gender")[
                "englishValue"
            ],
            "Female",
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(unavailable.status_code, 409)
        with self.app.state.session_factory() as session:
            reloaded = session.get(Voice, ready.id)
            assert reloaded is not None
            self.assertEqual(reloaded.normalized_title, "after")

    def test_sample_source_switch_validation_and_playback_permissions(self) -> None:
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            selectable = self.ready_audio(
                session,
                first,
                "Selectable",
                AudioVisibility.PUBLIC,
            )
            private_audio = self.ready_audio(
                session,
                first,
                "Private",
                AudioVisibility.PRIVATE,
            )
            failed_audio = AudioService(self.audio_storage).create_audio(
                session,
                author=first,
                title="Failed",
                source_type=AudioSourceType.CORPUS,
                text="Failed text",
            )
            AudioService(self.audio_storage).transition_status(
                session,
                failed_audio,
                AudioStatus.PROCESSING,
            )
            AudioService(self.audio_storage).transition_status(
                session,
                failed_audio,
                AudioStatus.FAILED,
                error_summary="failed",
            )
            failed_audio.visibility = AudioVisibility.PUBLIC
            private_voice = self.upload_voice(
                session,
                first,
                "Private voice",
                VoiceVisibility.PRIVATE,
            )
            public_voice = self.upload_voice(
                session,
                first,
                "Public voice",
                VoiceVisibility.PUBLIC,
            )
            session.commit()

        anonymous_original = self.send(
            "GET",
            f"/media/voice/{public_voice.id}/sample",
        )
        owner_original = self.send(
            "GET",
            f"/media/voice/{private_voice.id}/sample",
            headers=self.headers("first"),
        )
        teacher_original = self.send(
            "GET",
            f"/media/voice/{public_voice.id}/sample",
            headers=self.headers("second"),
        )
        hidden_original = self.send(
            "GET",
            f"/media/voice/{private_voice.id}/sample",
            headers=self.headers("second"),
        )
        private_rejected = self.send(
            "PATCH",
            f"/api/voices/{private_voice.id}",
            headers=self.headers("first"),
            json={
                "sampleSource": "public_audio",
                "sampleAudioId": private_audio.id,
            },
        )
        failed_rejected = self.send(
            "PATCH",
            f"/api/voices/{private_voice.id}",
            headers=self.headers("first"),
            json={
                "sampleSource": "public_audio",
                "sampleAudioId": failed_audio.id,
            },
        )
        missing_rejected = self.send(
            "PATCH",
            f"/api/voices/{private_voice.id}",
            headers=self.headers("first"),
            json={"sampleSource": "public_audio", "sampleAudioId": 999999},
        )
        selected = self.send(
            "PATCH",
            f"/api/voices/{private_voice.id}",
            headers=self.headers("first"),
            json={
                "sampleSource": "public_audio",
                "sampleAudioId": selectable.id,
            },
        )
        selected_sample = self.send(
            "GET",
            f"/media/voice/{private_voice.id}/sample",
            headers=self.headers("first"),
        )
        referenced_conflict = self.send(
            "PATCH",
            f"/api/audios/{selectable.id}",
            headers=self.headers("first"),
            json={"visibility": "private"},
        )
        restored = self.send(
            "PATCH",
            f"/api/voices/{private_voice.id}",
            headers=self.headers("first"),
            json={"sampleSource": "original"},
        )
        released = self.send(
            "PATCH",
            f"/api/audios/{selectable.id}",
            headers=self.headers("first"),
            json={"visibility": "private"},
        )

        self.assertEqual(anonymous_original.status_code, 401)
        self.assertEqual(owner_original.status_code, 200)
        self.assertEqual(teacher_original.status_code, 200)
        self.assertEqual(hidden_original.status_code, 404)
        self.assertEqual(private_rejected.status_code, 409)
        self.assertEqual(failed_rejected.status_code, 409)
        self.assertEqual(missing_rejected.status_code, 404)
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["sampleSource"], "public_audio")
        self.assertEqual(selected.json()["sampleAudioId"], selectable.id)
        self.assertEqual(selected_sample.status_code, 200)
        self.assertEqual(
            selected_sample.content,
            self.audio_storage.path(selectable.id).read_bytes(),
        )
        self.assertEqual(referenced_conflict.status_code, 409)
        self.assertEqual(
            referenced_conflict.json()["error"]["details"]["voiceIds"],
            [private_voice.id],
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["sampleSource"], "original")
        self.assertNotIn("sampleAudioId", restored.json())
        self.assertEqual(released.status_code, 200)
        self.assertEqual(
            {path.name for path in self.voice_storage.directory(private_voice.id).iterdir()},
            {"voice.pt", "reference.wav"},
        )

    def test_delete_checks_references_and_restores_on_failure(self) -> None:
        self.complete_profile("first", "TeacherOne")
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            deletable = self.upload_voice(
                session,
                first,
                "Delete me",
                VoiceVisibility.PRIVATE,
            )
            referenced = self.upload_voice(
                session,
                first,
                "Referenced",
                VoiceVisibility.PRIVATE,
            )
            compensation = self.upload_voice(
                session,
                first,
                "Restore on failure",
                VoiceVisibility.PRIVATE,
            )
            AudioService(self.audio_storage).create_audio(
                session,
                author=first,
                title="Uses voice",
                source_type=AudioSourceType.SINGLE_SPEAKER,
                utterances=[AudioUtteranceInput(referenced.id, "Speaker", "Text")],
            )
            session.commit()

        conflict = self.send(
            "DELETE",
            f"/api/voices/{referenced.id}",
            headers=self.headers("first"),
        )
        deleted = self.send(
            "DELETE",
            f"/api/voices/{deletable.id}",
            headers=self.headers("first"),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            conflict.json()["error"]["details"]["audioUtteranceCount"],
            1,
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(self.voice_storage.directory(deletable.id).exists())
        with self.app.state.session_factory() as session:
            self.assertIsNone(session.get(Voice, deletable.id))
            self.assertIsNotNone(session.get(Voice, referenced.id))

        class FailingRepository(VoiceRepository):
            def delete(self, session: Session, voice: Voice) -> None:
                raise RuntimeError("database write failed")

        with self.app.state.session_factory() as session:
            voice = session.get(Voice, compensation.id)
            assert voice is not None
            first = self.user(session, "TeacherOne")
            service = VoiceManagementService(
                self.voice_storage,
                self.audio_storage,
                repository=FailingRepository(),
            )
            with self.assertRaises(RuntimeError):
                service.delete(
                    session,
                    Principal(first),
                    compensation.id,
                    request_id="delete-failure",
                )
            self.assertTrue(self.voice_storage.directory(compensation.id).is_dir())
            self.assertIsNotNone(session.get(Voice, compensation.id))

    @staticmethod
    def _translation(language: str, value: str) -> TagTranslationInput:
        return TagTranslationInput(language=language, value=value)


if __name__ == "__main__":
    unittest.main()
