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
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus, VoiceVisibility
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_previews import (
    AUDIO_PREVIEW_JOB_TYPE,
    AudioPreviewService,
)
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.services.consistency import ConsistencyService
from backend.app.services.job_storage import JobStorage
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService
from backend.app.workers.audio_preview import AudioPreviewJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioPreviewIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'audio-previews.sqlite3'}"
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
            dialogue_silence_milliseconds=100,
        )
        self.app = create_app(self.settings)
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.job_storage = JobStorage(self.settings.data_dir)
        self.profile("first", "TeacherOne")
        self.profile("second", "TeacherTwo")
        self.voice_id = self.create_voice()

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
        self.assertEqual(response.status_code, 200)

    def create_voice(self) -> int:
        with self.app.state.session_factory() as session:
            owner = UserRepository().get_by_user_id(session, "TeacherOne")
            assert owner is not None
            service = VoiceService(self.voice_storage)
            voice = service.create_voice(session, author=owner, title="Preview voice")
            service.transition_status(session, voice, VoiceStatus.PROCESSING)
            self.voice_storage.path(voice.id, VoiceAsset.MODEL).write_bytes(b"voice")
            service.transition_status(session, voice, VoiceStatus.READY)
            service.set_visibility(session, voice, VoiceVisibility.PUBLIC)
            session.commit()
            return voice.id

    def submit_preview(self, speaker: str, text: str) -> httpx.Response:
        return self.send(
            "POST",
            "/api/audio-previews",
            headers=self.headers("first"),
            json={
                "voiceId": self.voice_id,
                "speakerDisplayName": speaker,
                "text": text,
            },
        )

    def worker(self, fake: FakeCosyVoiceIntegration) -> JobWorker:
        synthesis = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=fake,
        )
        service = AudioPreviewService(
            job_storage=self.job_storage,
            voice_storage=self.voice_storage,
            integration=fake,
            synthesis_service=synthesis,
        )
        return JobWorker(
            self.app.state.session_factory,
            {AUDIO_PREVIEW_JOB_TYPE: AudioPreviewJobHandler(service)},
            poll_interval_seconds=0.01,
            job_storage=self.job_storage,
        )

    def test_previews_are_generated_played_and_published_in_order(self) -> None:
        first = self.submit_preview("Woman", "First line.")
        second = self.submit_preview("Man", "Second line.")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        first_id = first.json()["jobId"]
        second_id = second.json()["jobId"]
        with self.app.state.session_factory() as session:
            job = session.get(Job, first_id)
            assert job is not None
            self.assertNotIn("text", job.input_summary)
            self.assertTrue(
                self.job_storage.audio_preview_input_path(first_id).is_file()
            )

        fake = FakeCosyVoiceIntegration()
        worker = self.worker(fake)
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        self.assertEqual(
            [call.text for call in fake.calls], ["First line.", "Second line."]
        )
        self.assertTrue(self.job_storage.audio_preview_path(first_id).is_file())
        self.assertFalse(self.job_storage.audio_preview_input_path(first_id).exists())

        media = self.send(
            "GET",
            f"/media/audio-preview/{first_id}",
            headers={**self.headers("first"), "Range": "bytes=0-15"},
        )
        hidden = self.send(
            "GET",
            f"/media/audio-preview/{first_id}",
            headers=self.headers("second"),
        )
        self.assertEqual(media.status_code, 206)
        self.assertEqual(hidden.status_code, 404)

        published = self.send(
            "POST",
            "/api/audios/from-previews",
            headers=self.headers("first"),
            json={
                "title": "Preview dialogue",
                "utterances": [
                    {
                        "previewJobId": second_id,
                        "voiceId": self.voice_id,
                        "speakerDisplayName": "Man",
                        "text": "Second line.",
                    },
                    {
                        "previewJobId": first_id,
                        "voiceId": self.voice_id,
                        "speakerDisplayName": "Woman",
                        "text": "First line.",
                    },
                ],
                "tagIds": [],
                "visibility": "public",
            },
        )
        self.assertEqual(published.status_code, 201, published.text)
        body = published.json()
        self.assertEqual(
            [item["text"] for item in body["utterances"]],
            ["Second line.", "First line."],
        )
        self.assertEqual(body["sourceType"], AudioSourceType.MULTI_TURN.value)
        self.assertEqual(body["status"], AudioStatus.READY.value)
        self.assertEqual(body["visibility"], AudioVisibility.PUBLIC.value)
        self.assertFalse(self.job_storage.directory(first_id).exists())
        self.assertFalse(self.job_storage.directory(second_id).exists())
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, body["id"])
            assert audio is not None
            self.assertGreater(audio.duration_seconds or 0, 0.2)

    def test_publish_rejects_stale_and_foreign_previews(self) -> None:
        response = self.submit_preview("Woman", "Original line.")
        job_id = response.json()["jobId"]
        self.assertTrue(self.worker(FakeCosyVoiceIntegration()).run_once())
        payload = {
            "title": "Rejected preview",
            "utterances": [
                {
                    "previewJobId": job_id,
                    "voiceId": self.voice_id,
                    "speakerDisplayName": "Woman",
                    "text": "Changed line.",
                }
            ],
            "tagIds": [],
            "visibility": "private",
        }
        stale = self.send(
            "POST",
            "/api/audios/from-previews",
            headers=self.headers("first"),
            json=payload,
        )
        foreign = self.send(
            "POST",
            "/api/audios/from-previews",
            headers=self.headers("second"),
            json={**payload, "title": "Foreign preview"},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(foreign.status_code, 404)

    def test_multiple_turns_with_one_speaker_publish_as_single_speaker(self) -> None:
        first_id = self.submit_preview("Narrator", "First part.").json()["jobId"]
        second_id = self.submit_preview("Narrator", "Second part.").json()["jobId"]
        worker = self.worker(FakeCosyVoiceIntegration())
        self.assertTrue(worker.run_once())
        self.assertTrue(worker.run_once())
        published = self.send(
            "POST",
            "/api/audios/from-previews",
            headers=self.headers("first"),
            json={
                "title": "One speaker sections",
                "utterances": [
                    {
                        "previewJobId": first_id,
                        "voiceId": self.voice_id,
                        "speakerDisplayName": "Narrator",
                        "text": "First part.",
                    },
                    {
                        "previewJobId": second_id,
                        "voiceId": self.voice_id,
                        "speakerDisplayName": "Narrator",
                        "text": "Second part.",
                    },
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(published.status_code, 201)
        self.assertEqual(published.json()["sourceType"], "single_speaker")
        self.assertEqual(len(published.json()["utterances"]), 2)

    def test_failed_preview_job_removes_staged_input(self) -> None:
        job_id = self.submit_preview("Woman", "Failure line.").json()["jobId"]
        worker = self.worker(
            FakeCosyVoiceIntegration(failure=RuntimeError("model details"))
        )
        self.assertTrue(worker.run_once())
        with self.app.state.session_factory() as session:
            job = session.get(Job, job_id)
            assert job is not None
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertNotIn("model details", job.error_summary or "")
        self.assertFalse(self.job_storage.directory(job_id).exists())

    def test_consistency_retains_only_valid_successful_preview_output(self) -> None:
        response = self.submit_preview("Woman", "Retained line.")
        job_id = response.json()["jobId"]
        self.assertTrue(self.worker(FakeCosyVoiceIntegration()).run_once())
        with self.app.state.session_factory() as session:
            report = ConsistencyService(self.settings.data_dir).run(session)
        self.assertFalse(
            any(
                issue.resource_type == "job" and issue.resource_id == job_id
                for issue in report.issues
            )
        )
        deleted = self.send(
            "DELETE",
            f"/api/audio-previews/{job_id}",
            headers=self.headers("first"),
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(self.job_storage.directory(job_id).exists())
