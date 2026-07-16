from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.generation_batch import GenerationBatchStatus
from backend.app.db.models.paper import PaperPreset
from backend.app.db.models.user import User
from backend.app.db.models.voice import VoiceSampleSource
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.generation_batches import GenerationBatchRepository
from backend.app.repositories.papers import PaperRepository
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audios import AudioService
from backend.app.services.jobs import JobService
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ResourceManagementIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'resource-management.sqlite3'}"
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
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.profile("first", "TeacherOne")
        self.profile("second", "TeacherTwo")

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers(subject: str = "first") -> dict[str, str]:
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

    def profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def write_wav(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(struct.pack("<h", 1000) * 800)

    def user(self, session: Session, user_id: str) -> User:
        user = UserRepository().get_by_user_id(session, user_id)
        assert user is not None
        return user

    def audio(
        self,
        session: Session,
        owner: User,
        title: str,
        *,
        status: AudioStatus = AudioStatus.READY,
        visibility: AudioVisibility = AudioVisibility.PRIVATE,
        tags: list[AudioTag] | None = None,
    ) -> Audio:
        service = AudioService(self.audio_storage)
        audio = service.create_audio(
            session,
            author=owner,
            title=title,
            source_type=AudioSourceType.CORPUS,
            text="Listening text",
            tags=tags or [],
        )
        service.transition_status(session, audio, AudioStatus.PROCESSING)
        if status is AudioStatus.READY:
            self.write_wav(self.audio_storage.path(audio.id))
            service.record_file_metadata(session, audio)
            service.transition_status(session, audio, AudioStatus.READY)
            service.set_visibility(session, audio, visibility)
        elif status is AudioStatus.FAILED:
            service.transition_status(
                session,
                audio,
                AudioStatus.FAILED,
                error_summary="Fixture failure",
            )
        return audio

    def seed(self) -> dict[str, int]:
        with self.app.state.session_factory() as session:
            first = self.user(session, "TeacherOne")
            second = self.user(session, "TeacherTwo")
            topic = AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="management",
            )
            owned = self.audio(
                session,
                first,
                "Owned private lesson",
                tags=[topic],
            )
            owned.created_at = datetime(2026, 1, 10, 12, 0, 0)
            failed = self.audio(
                session,
                first,
                "Owned failed lesson",
                status=AudioStatus.FAILED,
            )
            referenced = self.audio(
                session,
                first,
                "Referenced lesson",
                visibility=AudioVisibility.PUBLIC,
            )
            other = self.audio(session, second, "Other private lesson")
            voice = VoiceService(self.voice_storage).create_voice(
                session,
                author=first,
                title="Reference voice",
                sample_source=VoiceSampleSource.PUBLIC_AUDIO,
                sample_audio_id=referenced.id,
            )
            job = JobService().create_job(
                session,
                owner=first,
                job_type="management_fixture",
                input_summary={},
                retryable=False,
            )
            batch = GenerationBatchRepository().create(
                session,
                owner=first,
                job=job,
                question_types=["multiple_choice"],
                requested_count=1,
                tags=[topic],
                speaker_voices=[],
            )
            batch.status = GenerationBatchStatus.FAILED
            preset = session.scalar(
                select(PaperPreset).where(PaperPreset.is_builtin.is_(True))
            )
            assert preset is not None
            paper = PaperRepository().create_paper(
                session,
                owner=first,
                preset=preset,
                title="Managed paper",
                normalized_title="managed paper",
                audios=[owned],
            )
            session.commit()
            return {
                "owned": owned.id,
                "failed": failed.id,
                "referenced": referenced.id,
                "other": other.id,
                "voice": voice.id,
                "batch": batch.id,
                "paper": paper.id,
                "topic": topic.id,
            }

    def test_owned_lists_filter_dates_tags_and_report_references(self) -> None:
        values = self.seed()
        filtered = self.send(
            "GET",
            "/api/resource-management",
            headers=self.headers(),
            params={
                "kind": "audio",
                "page": 1,
                "page_size": 1,
                "status": "ready",
                "visibility": "private",
                "tagId": values["topic"],
                "created_from": "2026-01-10T00:00:00Z",
                "created_before": "2026-01-11T00:00:00Z",
                "q": "owned private",
            },
        )
        referenced = self.send(
            "GET",
            "/api/resource-management",
            headers=self.headers(),
            params={"kind": "audio", "q": "referenced"},
        )

        self.assertEqual(filtered.status_code, 200, filtered.text)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["id"], values["owned"])
        self.assertIn(
            values["topic"],
            {tag["id"] for tag in filtered.json()["items"][0]["tags"]},
        )
        self.assertEqual(referenced.json()["total"], 1)
        self.assertEqual(
            referenced.json()["items"][0]["references"],
            [{"type": "voice_sample", "count": 1}],
        )
        self.assertFalse(referenced.json()["items"][0]["canDelete"])

        for kind, expected_id in (
            ("voice", values["voice"]),
            ("generation_batch", values["batch"]),
            ("paper", values["paper"]),
        ):
            response = self.send(
                "GET",
                "/api/resource-management",
                headers=self.headers(),
                params={"kind": kind},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["items"][0]["id"], expected_id)

        invalid = self.send(
            "GET",
            "/api/resource-management",
            headers=self.headers(),
            params={"kind": "paper", "visibility": "private"},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_bulk_update_isolates_conflicts_and_other_owners(self) -> None:
        values = self.seed()

        response = self.send(
            "POST",
            "/api/resource-management/bulk-update",
            headers=self.headers(),
            json={
                "kind": "audio",
                "resourceIds": [values["owned"], values["failed"], values["other"]],
                "visibility": "public",
                "tagIds": [values["topic"]],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["successCount"], 1)
        self.assertEqual(response.json()["conflictCount"], 1)
        self.assertEqual(response.json()["failedCount"], 1)
        self.assertEqual(
            [item["outcome"] for item in response.json()["items"]],
            ["success", "conflict", "failed"],
        )
        with self.app.state.session_factory() as session:
            owned = session.get(Audio, values["owned"])
            failed = session.get(Audio, values["failed"])
            other = session.get(Audio, values["other"])
            assert owned and failed and other
            self.assertEqual(owned.visibility, AudioVisibility.PUBLIC)
            self.assertIn(values["topic"], {tag.id for tag in owned.tags})
            self.assertEqual(failed.visibility, AudioVisibility.PRIVATE)
            self.assertEqual(other.visibility, AudioVisibility.PRIVATE)
            self.assertNotIn(values["topic"], {tag.id for tag in other.tags})


if __name__ == "__main__":
    unittest.main()
