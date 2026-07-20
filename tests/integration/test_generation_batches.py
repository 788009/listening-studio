from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from backend.app.core.config import Settings
from backend.app.db.models.generation_batch import GenerationBatch, GenerationBatchStatus
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GenerationBatchIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'batches.sqlite3'}"
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
            max_corpus_bytes=128,
            max_batch_generation_count=6,
        )
        self.app = create_app(self.settings)
        self.storage = VoiceStorage(self.settings.data_dir)
        self.complete_profile()
        self.voice_ids = [self.create_voice("First voice"), self.create_voice("Second voice")]

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def headers() -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: "teacher",
        }

    @staticmethod
    async def request(app: FastAPI, method: str, path: str, **kwargs: object) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    def send(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(self.request(self.app, method, path, **kwargs))

    def complete_profile(self) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(),
            json={"userId": "TeacherOne", "username": "Teacher One"},
        )
        self.assertEqual(response.status_code, 200)

    def create_voice(self, title: str) -> int:
        with self.app.state.session_factory() as session:
            owner = UserRepository().get_by_user_id(session, "TeacherOne")
            assert owner is not None
            service = VoiceService(self.storage)
            voice = service.create_voice(session, author=owner, title=title)
            service.transition_status(session, voice, VoiceStatus.PROCESSING)
            self.storage.path(voice.id, VoiceAsset.MODEL).write_bytes(b"voice")
            service.transition_status(session, voice, VoiceStatus.READY)
            session.commit()
            return voice.id

    def submit(
        self,
        question_type_counts: dict[str, int],
        speakers: int,
    ) -> httpx.Response:
        fields: list[tuple[str, tuple[None, str]]] = [
            ("questionTypeCounts", (None, json.dumps(question_type_counts))),
            ("corpus", (None, "A short source corpus.")),
            (
                "speakerVoiceMap",
                (
                    None,
                    json.dumps(
                        {
                            f"Speaker {index + 1}": self.voice_ids[index]
                            for index in range(speakers)
                        }
                    ),
                ),
            ),
        ]
        return self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers(),
            files=fields,
        )

    def test_submission_stages_corpus_without_precreating_draft_items(self) -> None:
        response = self.submit({"short_dialogue": 2, "monologue": 1}, 2)
        self.assertEqual(response.status_code, 202, response.text)
        batch_id = response.json()["batchId"]
        job_id = response.json()["jobId"]

        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            job = session.get(Job, job_id)
            assert batch is not None and job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.PENDING)
            self.assertEqual(
                batch.question_type_counts,
                {"short_dialogue": 2, "monologue": 1},
            )
            self.assertEqual(batch.items, [])
            self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(
            (self.root / "data" / "jobs" / str(job_id) / "corpus.txt").read_text(),
            "A short source corpus.",
        )

    def test_dialogue_requires_two_speakers_and_counts_are_positive(self) -> None:
        one_speaker = self.submit({"long_dialogue": 1}, 1)
        zero_count = self.submit({"short_dialogue": 0, "monologue": 1}, 2)
        monologue = self.submit({"monologue": 1}, 1)

        self.assertEqual(one_speaker.status_code, 422)
        self.assertEqual(zero_count.status_code, 422)
        self.assertEqual(monologue.status_code, 202, monologue.text)

    def test_rejects_invalid_question_type_and_file_encoding(self) -> None:
        invalid_type = self.submit({"multiple_choice": 1}, 1)
        invalid_file = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers(),
            files=[
                ("questionTypeCounts", (None, json.dumps({"monologue": 1}))),
                ("encoding", (None, "latin-1")),
                ("file", ("corpus.txt", b"source", "text/plain")),
                ("speakerVoiceMap", (None, json.dumps({"Narrator": self.voice_ids[0]}))),
            ],
        )
        self.assertEqual(invalid_type.status_code, 422)
        self.assertEqual(invalid_file.status_code, 422)


if __name__ == "__main__":
    unittest.main()
