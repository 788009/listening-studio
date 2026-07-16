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
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchStatus,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.services.audio_tags import AudioTagService


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
            max_batch_generation_count=3,
        )
        self.app = create_app(self.settings)
        self.complete_profile("first", "TeacherOne")
        self.complete_profile("second", "TeacherTwo")
        with self.app.state.session_factory() as session:
            service = AudioTagService()
            self.topic = service.create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="climate_change",
            )
            self.category = service.create_user_tag(
                session,
                tag_type=AudioTagType.CATEGORY,
                english_value="lecture",
            )
            self.speaker = service.create_user_tag(
                session,
                tag_type=AudioTagType.SPEAKER,
                english_value="host",
            )
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

    def complete_profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def text_form(
        corpus: str,
        *,
        count: str = "2",
        tag_ids: list[int] | None = None,
    ) -> list[tuple[str, tuple[None, str]]]:
        fields = [
            ("questionTypes", (None, "multiple_choice")),
            ("questionTypes", (None, "short_answer")),
            ("count", (None, count)),
            ("corpus", (None, corpus)),
        ]
        fields.extend(("tagIds", (None, str(tag_id))) for tag_id in tag_ids or [])
        return fields

    def test_text_submission_creates_owned_batch_job_items_and_fixed_file(self) -> None:
        corpus = "A short corpus about climate."
        response = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers("first"),
            files=self.text_form(
                corpus,
                tag_ids=[self.topic.id, self.category.id],
            ),
        )

        self.assertEqual(response.status_code, 202, response.text)
        identifiers = response.json()
        batch_id = identifiers["batchId"]
        job_id = identifiers["jobId"]
        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            job = session.get(Job, job_id)
            assert batch is not None and job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.PENDING)
            self.assertEqual(batch.requested_count, 2)
            self.assertEqual(
                batch.question_types,
                ["multiple_choice", "short_answer"],
            )
            self.assertEqual(job.status, JobStatus.QUEUED)
            self.assertEqual(job.type, "corpus_generation")
            self.assertEqual(job.input_summary, {"batchId": batch_id})
            self.assertNotIn(corpus, str(job.input_summary))

        directory = self.root / "data" / "jobs" / str(job_id)
        self.assertEqual(
            sorted(path.name for path in directory.iterdir()),
            ["corpus.txt"],
        )
        self.assertEqual((directory / "corpus.txt").read_text(), corpus)

        detail = self.send(
            "GET",
            f"/api/generation-batches/{batch_id}",
            headers=self.headers("first"),
        )
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual([item["position"] for item in payload["items"]], [0, 1])
        self.assertEqual(
            [tag["type"] for tag in payload["tags"]],
            ["topic", "category"],
        )
        self.assertNotIn("corpus", payload)
        linked_tag_delete = self.send(
            "DELETE",
            f"/api/audio-tags/{self.topic.id}",
            headers=self.headers("first"),
        )
        self.assertEqual(linked_tag_delete.status_code, 409)
        self.assertEqual(
            linked_tag_delete.json()["error"]["details"]["usageCount"],
            1,
        )

    def test_utf16_txt_is_normalized_and_original_filename_is_not_used(self) -> None:
        corpus = "Line one.\nLine two."
        fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
            ("questionTypes", (None, "true_false")),
            ("count", (None, "1")),
            ("encoding", (None, "utf-16")),
            ("file", ("private-name.txt", corpus.encode("utf-16"), "text/plain")),
        ]
        response = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers("first"),
            files=fields,
        )

        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["jobId"]
        directory = self.root / "data" / "jobs" / str(job_id)
        self.assertFalse((directory / "private-name.txt").exists())
        self.assertEqual((directory / "corpus.txt").read_text(), corpus)

    def test_batch_reads_are_owner_scoped(self) -> None:
        created = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers("first"),
            files=self.text_form("Owner-only corpus.", count="1"),
        )
        batch_id = created.json()["batchId"]

        anonymous = self.send("GET", "/api/generation-batches")
        hidden = self.send(
            "GET",
            f"/api/generation-batches/{batch_id}",
            headers=self.headers("second"),
        )
        other_list = self.send(
            "GET",
            "/api/generation-batches",
            headers=self.headers("second"),
        )
        owner_list = self.send(
            "GET",
            "/api/generation-batches",
            headers=self.headers("first"),
        )

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(other_list.json()["total"], 0)
        self.assertEqual(owner_list.json()["total"], 1)

    def test_invalid_corpus_count_and_tags_are_rejected_without_records(self) -> None:
        FormPart = tuple[str, tuple[None, str] | tuple[str, bytes, str]]
        cases: list[tuple[str, list[FormPart]]] = [
            ("empty", self.text_form("   ", count="1")),
            ("binary", self.text_form("text\x00data", count="1")),
            ("count", self.text_form("Valid corpus", count="4")),
            (
                "speaker-tag",
                self.text_form("Valid corpus", count="1", tag_ids=[self.speaker.id]),
            ),
            (
                "file-type",
                [
                    ("questionTypes", (None, "short_answer")),
                    ("count", (None, "1")),
                    ("encoding", (None, "utf-8")),
                    ("file", ("corpus.csv", b"Valid corpus", "text/csv")),
                ],
            ),
            (
                "encoding",
                [
                    ("questionTypes", (None, "short_answer")),
                    ("count", (None, "1")),
                    ("encoding", (None, "latin-1")),
                    ("file", ("corpus.txt", b"Valid corpus", "text/plain")),
                ],
            ),
            (
                "encoding-mismatch",
                [
                    ("questionTypes", (None, "short_answer")),
                    ("count", (None, "1")),
                    ("encoding", (None, "utf-8")),
                    ("file", ("corpus.txt", b"\xff\xfe", "text/plain")),
                ],
            ),
            ("size", self.text_form("x" * 129, count="1")),
        ]

        for name, fields in cases:
            with self.subTest(name=name):
                response = self.send(
                    "POST",
                    "/api/generation-batches",
                    headers=self.headers("first"),
                    files=fields,
                )
                self.assertEqual(response.status_code, 422, response.text)

        with self.app.state.session_factory() as session:
            self.assertEqual(session.query(GenerationBatch).count(), 0)

    def test_text_and_file_are_mutually_exclusive_and_file_needs_encoding(self) -> None:
        both = self.text_form("Text corpus", count="1")
        both.append(("file", ("corpus.txt", b"File corpus", "text/plain")))
        both_response = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers("first"),
            files=both,
        )
        no_encoding = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers("first"),
            files=[
                ("questionTypes", (None, "fill_in_blank")),
                ("count", (None, "1")),
                ("file", ("corpus.txt", b"File corpus", "text/plain")),
            ],
        )

        self.assertEqual(both_response.status_code, 422)
        self.assertEqual(no_encoding.status_code, 422)


if __name__ == "__main__":
    unittest.main()
