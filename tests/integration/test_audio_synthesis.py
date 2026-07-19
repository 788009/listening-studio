from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus, VoiceVisibility
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService
from backend.app.workers.audio_synthesis import AudioSynthesisJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioSynthesisIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'audio-synthesis.sqlite3'}"
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

    def create_voice(
        self,
        *,
        user_id: str,
        title: str,
        status: VoiceStatus = VoiceStatus.READY,
        visibility: VoiceVisibility = VoiceVisibility.PRIVATE,
    ) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, user_id)
            assert user is not None
            service = VoiceService(self.voice_storage)
            voice = service.create_voice(session, author=user, title=title)
            service.transition_status(session, voice, VoiceStatus.PROCESSING)
            if status is VoiceStatus.READY:
                self.voice_storage.path(voice.id, VoiceAsset.MODEL).write_bytes(
                    b"voice-model"
                )
                service.transition_status(session, voice, VoiceStatus.READY)
                service.set_visibility(session, voice, visibility)
            elif status is VoiceStatus.FAILED:
                service.transition_status(
                    session,
                    voice,
                    VoiceStatus.FAILED,
                    error_summary="Voice failed",
                )
            session.commit()
            return voice.id

    def create_request(
        self,
        voice_id: int,
        *,
        subject: str = "first",
        speaker_display_name: str | None = None,
        tag_ids: list[int] | None = None,
        visibility: str = "public",
        request_id: str | None = None,
    ) -> httpx.Response:
        headers = self.headers(subject)
        if request_id is not None:
            headers["X-Request-ID"] = request_id
        return self.send(
            "POST",
            "/api/audios",
            headers=headers,
            json={
                "title": "Morning practice",
                "text": "  Good morning, class.  ",
                "voiceId": voice_id,
                "speakerDisplayName": speaker_display_name,
                "tagIds": tag_ids or [],
                "visibility": visibility,
            },
        )

    def worker(self, fake: FakeCosyVoiceIntegration) -> JobWorker:
        service = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=fake,
        )
        return JobWorker(
            self.app.state.session_factory,
            {AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(service)},
            poll_interval_seconds=0.01,
        )

    def test_single_speaker_job_generates_metadata_tags_and_is_idempotent(
        self,
    ) -> None:
        voice_id = self.create_voice(user_id="TeacherOne", title="Calm voice")
        with self.app.state.session_factory() as session:
            topic = AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="Morning Routine",
            )
            session.commit()
            topic_id = topic.id
        fake = FakeCosyVoiceIntegration()

        response = self.create_request(
            voice_id,
            speaker_display_name="Woman",
            tag_ids=[topic_id],
        )

        self.assertEqual(response.status_code, 202)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        self.assertEqual(fake.calls, [])
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.PENDING)
            self.assertEqual(audio.visibility, AudioVisibility.PRIVATE)
            self.assertEqual(audio.source_type, AudioSourceType.SINGLE_SPEAKER)
            self.assertEqual(audio.text, "Good morning, class.")
            self.assertEqual(len(audio.utterances), 1)
            self.assertEqual(audio.utterances[0].voice_id, voice_id)
            self.assertEqual(audio.utterances[0].speaker_display_name, "Woman")
            self.assertEqual(
                {(tag.type, tag.value) for tag in audio.tags},
                {
                    (AudioTagType.AUTHOR, "TeacherOne"),
                    (AudioTagType.SPEAKER, "Calm_voice"),
                    (AudioTagType.TOPIC, "Morning_Routine"),
                },
            )
            self.assertEqual(job.status, JobStatus.QUEUED)
            self.assertNotIn("text", job.input_summary)

        worker = self.worker(fake)
        self.assertTrue(worker.run_once())

        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call.operation, "synthesize")
        self.assertEqual(
            call.input_path,
            self.voice_storage.path(voice_id, VoiceAsset.MODEL),
        )
        self.assertEqual(call.text, "Good morning, class.")
        self.assertEqual(
            call.output_path,
            self.audio_storage.job_directory(job_id) / "audio.wav",
        )
        self.assertFalse(self.audio_storage.job_directory(job_id).exists())
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.READY)
            self.assertEqual(audio.visibility, AudioVisibility.PUBLIC)
            self.assertEqual(audio.audio_format, "wav")
            self.assertAlmostEqual(audio.duration_seconds or 0, 0.1)
            self.assertEqual(audio.sample_rate, 8000)

            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(job.result_type, "audio")
            self.assertEqual(job.result_id, audio_id)
            job.status = JobStatus.QUEUED
            job.progress = 0
            job.result_type = None
            job.result_id = None
            job.finished_at = None
            session.commit()

        self.assertTrue(worker.run_once())
        self.assertEqual(len(fake.calls), 1)

        search = self.send(
            "GET",
            "/api/audios",
            params={"q": "speaker:Calm_voice"},
        )
        self.assertEqual(search.status_code, 200)
        self.assertEqual(
            [item["id"] for item in search.json()["items"]],
            [audio_id],
        )

    def test_voice_access_rules_are_checked_before_records_are_created(self) -> None:
        other_private = self.create_voice(
            user_id="TeacherTwo",
            title="Other private",
        )
        other_public = self.create_voice(
            user_id="TeacherTwo",
            title="Other public",
            visibility=VoiceVisibility.PUBLIC,
        )
        failed = self.create_voice(
            user_id="TeacherOne",
            title="Failed",
            status=VoiceStatus.FAILED,
        )
        processing = self.create_voice(
            user_id="TeacherOne",
            title="Processing",
            status=VoiceStatus.PROCESSING,
        )

        self.assertEqual(self.create_request(other_private).status_code, 404)
        self.assertEqual(self.create_request(failed).status_code, 409)
        self.assertEqual(self.create_request(processing).status_code, 409)
        accepted = self.create_request(other_public)
        self.assertEqual(accepted.status_code, 202)

        with self.app.state.session_factory() as session:
            audio_count = session.scalar(select(func.count()).select_from(Audio))
            job_count = session.scalar(select(func.count()).select_from(Job))
            self.assertEqual(audio_count, 1)
            self.assertEqual(job_count, 1)

    def test_retry_completes_an_atomically_written_file_without_model_call(
        self,
    ) -> None:
        voice_id = self.create_voice(user_id="TeacherOne", title="Retry voice")
        response = self.create_request(voice_id, visibility="private")
        self.assertEqual(response.status_code, 202)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        temporary = self.audio_storage.temporary_audio_path(job_id)
        seed = self.root / "seed-voice.pt"
        seed.write_bytes(b"voice")
        FakeCosyVoiceIntegration().synthesize(seed, "seed", temporary)
        self.audio_storage.atomic_replace(audio_id, job_id)
        fake = FakeCosyVoiceIntegration()

        self.assertTrue(self.worker(fake).run_once())

        self.assertEqual(fake.calls, [])
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.READY)
            self.assertEqual(audio.sample_rate, 8000)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)

    def test_worker_failure_marks_audio_and_job_and_cleans_files(self) -> None:
        voice_id = self.create_voice(user_id="TeacherOne", title="Failure voice")
        response = self.create_request(
            voice_id,
            visibility="private",
            request_id="failed-submit",
        )
        self.assertEqual(response.status_code, 202)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        fake = FakeCosyVoiceIntegration(failure=RuntimeError("model details"))

        self.assertTrue(self.worker(fake).run_once())

        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.FAILED)
            self.assertEqual(audio.visibility, AudioVisibility.PRIVATE)
            self.assertNotIn("model details", audio.error_summary or "")
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertIn("Verify the selected voice", job.error_summary or "")
        self.assertFalse(self.audio_storage.directory(audio_id).exists())
        self.assertFalse(self.audio_storage.job_directory(job_id).exists())
        log_lines = (self.settings.log_dir / "backend.log").read_text(
            encoding="utf-8"
        ).splitlines()
        shared_context = (
            f"job_id={job_id} user_db_id=1 resource_type=audio "
            f"resource_id={audio_id}"
        )
        self.assertTrue(
            any(
                "request_id=failed-submit" in line
                and shared_context in line
                and "Audio synthesis submitted" in line
                for line in log_lines
            )
        )
        self.assertTrue(
            any(
                f"request_id=job-{job_id}" in line
                and shared_context in line
                and "Job started" in line
                for line in log_lines
            )
        )
        self.assertTrue(
            any(
                f"request_id=job-{job_id}" in line
                and shared_context in line
                and "Audio synthesis failed" in line
                for line in log_lines
            )
        )


if __name__ == "__main__":
    unittest.main()
