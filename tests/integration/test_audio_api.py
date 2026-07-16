from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.user import User
from backend.app.db.models.voice import VoiceExampleMode
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audios import AudioService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioApiIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'audio-api.sqlite3'}"
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
    async def request(app: FastAPI, method: str, path: str, **kwargs: object):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def profile(self) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(),
            json={"userId": "TeacherOne", "username": "Teacher"},
        )
        self.assertEqual(response.status_code, 200)

    def user(self, session: Session) -> User:
        user = UserRepository().get_by_user_id(session, "TeacherOne")
        assert user is not None
        return user

    def ready_audio(
        self,
        session: Session,
        user: User,
        title: str,
        visibility: AudioVisibility,
    ) -> Audio:
        service = AudioService(self.storage)
        audio = service.create_audio(
            session,
            author=user,
            title=title,
            source_type=AudioSourceType.CORPUS,
            text="Listening text",
        )
        service.transition_status(session, audio, AudioStatus.PROCESSING)
        voice_file = self.root / f"voice-{audio.id}.pt"
        voice_file.write_bytes(b"voice")
        output = self.storage.temporary_audio_path(audio.id)
        FakeCosyVoiceIntegration().synthesize(voice_file, "text", output)
        self.storage.atomic_replace(audio.id, audio.id)
        service.record_file_metadata(session, audio)
        service.transition_status(session, audio, AudioStatus.READY)
        service.set_visibility(session, audio, visibility)
        session.commit()
        return audio

    def test_visibility_range_missing_and_empty_media(self) -> None:
        self.profile()
        with self.app.state.session_factory() as session:
            user = self.user(session)
            public = self.ready_audio(session, user, "Public", AudioVisibility.PUBLIC)
            private = self.ready_audio(
                session,
                user,
                "Private",
                AudioVisibility.PRIVATE,
            )

        listed = self.send("GET", "/api/audios")
        full = self.send("GET", f"/media/audio/{public.id}")
        partial = self.send(
            "GET",
            f"/media/audio/{public.id}",
            headers={"Range": "bytes=0-9"},
        )
        suffix = self.send(
            "GET",
            f"/media/audio/{public.id}",
            headers={"Range": "bytes=-10"},
        )
        invalid = self.send(
            "GET",
            f"/media/audio/{public.id}",
            headers={"Range": "bytes=999999-"},
        )
        hidden = self.send("GET", f"/media/audio/{private.id}")
        owner = self.send(
            "GET",
            f"/media/audio/{private.id}",
            headers=self.headers(),
        )

        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.headers["content-type"], "audio/wav")
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(len(partial.content), 10)
        self.assertTrue(partial.headers["content-range"].startswith("bytes 0-9/"))
        self.assertEqual(suffix.status_code, 206)
        self.assertEqual(len(suffix.content), 10)
        self.assertEqual(invalid.status_code, 416)
        self.assertTrue(invalid.headers["content-range"].startswith("bytes */"))
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(owner.status_code, 200)

        self.storage.path(public.id).unlink()
        missing = self.send("GET", f"/media/audio/{public.id}")
        self.assertEqual(missing.status_code, 404)
        self.storage.path(private.id).write_bytes(b"")
        empty = self.send(
            "GET",
            f"/media/audio/{private.id}",
            headers=self.headers(),
        )
        self.assertEqual(empty.status_code, 409)

    def test_update_references_and_delete(self) -> None:
        self.profile()
        with self.app.state.session_factory() as session:
            user = self.user(session)
            topic = AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="Climate",
            )
            referenced = self.ready_audio(
                session, user, "Referenced", AudioVisibility.PUBLIC
            )
            deletable = self.ready_audio(
                session, user, "Deletable", AudioVisibility.PRIVATE
            )
            voice = VoiceService(VoiceStorage(self.settings.data_dir)).create_voice(
                session,
                author=user,
                title="Uses audio",
                example_mode=VoiceExampleMode.AUDIO,
                example_audio_id=referenced.id,
            )
            processing = AudioService(self.storage).create_audio(
                session,
                author=user,
                title="Processing",
                source_type=AudioSourceType.CORPUS,
                text="Text",
            )
            AudioService(self.storage).transition_status(
                session, processing, AudioStatus.PROCESSING
            )
            session.commit()

        updated = self.send(
            "PATCH",
            f"/api/audios/{deletable.id}",
            headers=self.headers(),
            json={"title": "Ａfter", "tagIds": [topic.id]},
        )
        make_private = self.send(
            "PATCH",
            f"/api/audios/{referenced.id}",
            headers=self.headers(),
            json={"visibility": "private"},
        )
        referenced_delete = self.send(
            "DELETE", f"/api/audios/{referenced.id}", headers=self.headers()
        )
        active_delete = self.send(
            "DELETE", f"/api/audios/{processing.id}", headers=self.headers()
        )
        deleted = self.send(
            "DELETE", f"/api/audios/{deletable.id}", headers=self.headers()
        )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "After")
        self.assertEqual(
            {tag["type"] for tag in updated.json()["tags"]},
            {"author", "topic"},
        )
        self.assertEqual(make_private.status_code, 409)
        self.assertEqual(make_private.json()["error"]["details"]["voiceIds"], [
            voice.id
        ])
        self.assertEqual(referenced_delete.status_code, 409)
        self.assertEqual(active_delete.status_code, 409)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(self.storage.directory(deletable.id).exists())
        with self.app.state.session_factory() as session:
            self.assertIsNone(session.get(Audio, deletable.id))
            reloaded = session.get(Audio, referenced.id)
            assert reloaded is not None
            self.assertEqual(reloaded.visibility, AudioVisibility.PUBLIC)


if __name__ == "__main__":
    unittest.main()
