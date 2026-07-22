from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from backend.app.core.config import Settings
from backend.app.db.models.audio import AudioSourceType, AudioStatus, AudioVisibility
from backend.app.db.models.user import UserRole
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.assemblies import ASSEMBLY_JOB_TYPE, AssemblyService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioQuestionInput, AudioService
from backend.app.workers.assemblies import AssemblyJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AssemblyIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'assemblies.sqlite3'}"
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
        self.profile("user", "AssemblyTeacher")
        self.profile("admin", "TemplateAdmin")
        with self.app.state.session_factory() as session:
            admin = UserRepository().get_by_user_id(session, "TemplateAdmin")
            assert admin is not None
            admin.role = UserRole.ADMIN
            session.commit()

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

    def profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def ready_audio(self, title: str, question_count: int, text: str) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, "AssemblyTeacher")
            assert user is not None
            service = AudioService(self.storage)
            audio = service.create_audio(
                session,
                author=user,
                title=title,
                source_type=AudioSourceType.CORPUS,
                text=text,
                questions=[
                    AudioQuestionInput(
                        f"Question {position + 1}?",
                        ("Correct",),
                        ("Incorrect",),
                    )
                    for position in range(question_count)
                ],
            )
            service.transition_status(session, audio, AudioStatus.PROCESSING)
            self.write_wav(self.storage.path(audio.id), 100)
            service.record_file_metadata(session, audio)
            service.transition_status(session, audio, AudioStatus.READY)
            service.set_visibility(session, audio, AudioVisibility.PUBLIC)
            session.commit()
            return audio.id

    @staticmethod
    def write_wav(path: Path, duration_milliseconds: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = 8000 * duration_milliseconds // 1000
        frames = struct.pack("<h", 1000) * frame_count
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(frames)

    def test_dynamic_smart_segment_and_metadata_assembly(self) -> None:
        previous = self.ready_audio("Nine questions", 9, "Excluded text")
        placeholder = self.ready_audio("Two questions", 2, "Included text")
        prefix = self.ready_audio("pre_10-11", 0, "Question numbers")

        response = self.send(
            "POST",
            "/api/assemblies",
            headers=self.headers("user"),
            json={
                "title": "Dynamic full paper",
                "segments": [
                    {
                        "type": "audio",
                        "audioId": previous,
                        "repeatCount": 2,
                        "repeatIntervalMilliseconds": 50,
                        "includeText": False,
                    },
                    {"type": "smart", "includeText": False},
                    {"type": "placeholder", "audioId": placeholder},
                    {"type": "silence", "silenceMilliseconds": 25},
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        worker = JobWorker(
            self.app.state.session_factory,
            {ASSEMBLY_JOB_TYPE: AssemblyJobHandler(AssemblyService(self.storage))},
            poll_interval_seconds=0.01,
        )
        self.assertTrue(worker.run_once())

        detail = self.send(
            "GET",
            f"/api/audios/{audio_id}",
            headers=self.headers("user"),
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["sourceType"], "assembly")
        self.assertEqual(body["text"], "Included text")
        self.assertEqual(len(body["questions"]), 11)
        self.assertIn(
            ("category", "full_paper"),
            {(tag["type"], tag["englishValue"]) for tag in body["tags"]},
        )
        self.assertIn(
            ("other", "11_question"),
            {(tag["type"], tag["englishValue"]) for tag in body["tags"]},
        )
        with wave.open(str(self.storage.path(audio_id)), "rb") as output:
            self.assertAlmostEqual(output.getnframes() / 8000, 0.475, delta=0.02)
        self.assertTrue(self.storage.path(prefix).is_file())
        self.assertFalse(self.storage.job_directory(job_id).exists())

        with self.app.state.session_factory() as session:
            retried = AssemblyService(self.storage).process(
                session,
                audio_id=audio_id,
                job_id=job_id,
                owner_id=1,
                visibility=AudioVisibility.PRIVATE,
                segments=[],
                checkpoint=lambda progress: None,
            )
            self.assertEqual(retried.id, audio_id)

        draft = self.send(
            "GET",
            f"/api/audios/{audio_id}/creation-draft",
            headers=self.headers("user"),
        )
        self.assertEqual(draft.status_code, 409)

    def test_only_admin_can_create_templates(self) -> None:
        payload = {
            "title": "Structured exam",
            "segments": [
                {"type": "smart"},
                {"type": "placeholder", "suggestedQuery": "topic:news"},
            ],
        }
        forbidden = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("user"),
            json=payload,
        )
        created = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("admin"),
            json=payload,
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(
            created.json()["segments"][1]["suggestedQuery"],
            "topic:news",
        )


if __name__ == "__main__":
    unittest.main()
