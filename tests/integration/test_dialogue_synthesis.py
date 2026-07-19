from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
import wave
from collections.abc import Callable
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus, VoiceVisibility
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceCall
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService
from backend.app.workers.audio_synthesis import AudioSynthesisJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FixtureSynthesisIntegration:
    def __init__(
        self,
        *,
        fail_on_call: int | None = None,
        after_call: Callable[[int], None] | None = None,
    ) -> None:
        self.fail_on_call = fail_on_call
        self.after_call = after_call
        self.calls: list[FakeCosyVoiceCall] = []

    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        raise NotImplementedError

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        call_number = len(self.calls) + 1
        self.calls.append(
            FakeCosyVoiceCall(
                "synthesize",
                Path(voice_path),
                Path(output_audio_path),
                text,
            )
        )
        if self.fail_on_call == call_number:
            raise RuntimeError("fixture synthesis failed")
        configurations = {
            "First line.": (8000, 1, 2, 100),
            "Again.": (8000, 1, 2, 50),
            "Last line.": (16000, 2, 1, 200),
        }
        sample_rate, channels, sample_width, duration_ms = configurations.get(
            text,
            (8000, 1, 2, 100),
        )
        frame_count = sample_rate * duration_ms // 1000
        if sample_width == 2:
            frames = struct.pack("<h", 1000) * frame_count * channels
        else:
            frames = bytes([192]) * frame_count * channels
        with wave.open(str(output_audio_path), "wb") as audio_file:
            audio_file.setnchannels(channels)
            audio_file.setsampwidth(sample_width)
            audio_file.setframerate(sample_rate)
            audio_file.writeframes(frames)
        if self.after_call is not None:
            self.after_call(call_number)
        return Path(output_audio_path)


class DialogueSynthesisIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'dialogue.sqlite3'}"
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
            dialogue_silence_milliseconds=50,
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
        user_id: str,
        title: str,
        *,
        visibility: VoiceVisibility = VoiceVisibility.PRIVATE,
    ) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, user_id)
            assert user is not None
            service = VoiceService(self.voice_storage)
            voice = service.create_voice(session, author=user, title=title)
            service.transition_status(session, voice, VoiceStatus.PROCESSING)
            self.voice_storage.path(voice.id, VoiceAsset.MODEL).write_bytes(
                b"voice-model"
            )
            service.transition_status(session, voice, VoiceStatus.READY)
            service.set_visibility(session, voice, visibility)
            session.commit()
            return voice.id

    def dialogue(
        self,
        utterances: list[dict[str, object]],
        *,
        subject: str = "first",
    ) -> httpx.Response:
        return self.send(
            "POST",
            "/api/audios/dialogues",
            headers=self.headers(subject),
            json={
                "title": "Dialogue practice",
                "utterances": utterances,
                "visibility": "public",
            },
        )

    @staticmethod
    def utterance(voice_id: int, speaker: str, text: str) -> dict[str, object]:
        return {
            "voiceId": voice_id,
            "speakerDisplayName": speaker,
            "text": text,
        }

    def worker(self, integration: FixtureSynthesisIntegration) -> JobWorker:
        service = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=integration,
        )
        return JobWorker(
            self.app.state.session_factory,
            {AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(service)},
            poll_interval_seconds=0.01,
        )

    def test_dialogue_preserves_order_silence_format_and_speaker_tags(self) -> None:
        first_voice = self.create_voice("TeacherOne", "First voice")
        second_voice = self.create_voice(
            "TeacherTwo",
            "Second voice",
            visibility=VoiceVisibility.PUBLIC,
        )
        response = self.dialogue(
            [
                self.utterance(first_voice, "Alice", "First line."),
                self.utterance(first_voice, "Alice", "Again."),
                self.utterance(second_voice, "Bob", "Last line."),
            ]
        )
        self.assertEqual(response.status_code, 202)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(
                audio.text,
                "Alice: First line.\nAlice: Again.\nBob: Last line.",
            )
            self.assertEqual(
                [item.voice_id for item in audio.utterances],
                [first_voice, first_voice, second_voice],
            )
            self.assertEqual(
                {(tag.type, tag.value) for tag in audio.tags},
                {
                    (AudioTagType.AUTHOR, "TeacherOne"),
                    (AudioTagType.SPEAKER, "First_voice"),
                    (AudioTagType.SPEAKER, "Second_voice"),
                },
            )
            self.assertEqual(job.input_summary["silenceMilliseconds"], 50)
            self.assertNotIn("utterances", job.input_summary)

        integration = FixtureSynthesisIntegration()
        self.assertTrue(self.worker(integration).run_once())

        self.assertEqual(
            [call.input_path for call in integration.calls],
            [
                self.voice_storage.path(first_voice, VoiceAsset.MODEL),
                self.voice_storage.path(first_voice, VoiceAsset.MODEL),
                self.voice_storage.path(second_voice, VoiceAsset.MODEL),
            ],
        )
        output = self.audio_storage.path(audio_id)
        with wave.open(str(output), "rb") as audio_file:
            self.assertEqual(audio_file.getframerate(), 8000)
            self.assertEqual(audio_file.getnchannels(), 1)
            self.assertEqual(audio_file.getsampwidth(), 2)
            frame_count = audio_file.getnframes()
            samples = struct.unpack(
                f"<{frame_count}h",
                audio_file.readframes(frame_count),
            )
        self.assertAlmostEqual(frame_count / 8000, 0.45, delta=0.01)
        self.assertGreater(self._peak(samples, 0, 80), 0)
        self.assertEqual(self._peak(samples, 110, 140), 0)
        self.assertGreater(self._peak(samples, 160, 190), 0)
        self.assertEqual(self._peak(samples, 210, 240), 0)
        self.assertGreater(self._peak(samples, 280, 400), 0)
        self.assertEqual(
            [path.name for path in output.parent.iterdir()],
            ["audio.wav"],
        )
        self.assertFalse(self.audio_storage.job_directory(job_id).exists())

    def test_empty_or_inaccessible_dialogue_creates_no_audio_or_job(self) -> None:
        own_voice = self.create_voice("TeacherOne", "Own voice")
        private_other = self.create_voice("TeacherTwo", "Private other")

        empty = self.dialogue([])
        inaccessible = self.dialogue(
            [
                self.utterance(own_voice, "Alice", "First line."),
                self.utterance(private_other, "Bob", "Last line."),
            ]
        )

        self.assertEqual(empty.status_code, 422)
        self.assertEqual(inaccessible.status_code, 404)
        with self.app.state.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Audio)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Job)), 0)

    def test_middle_turn_failure_cleans_all_segments(self) -> None:
        voice_id = self.create_voice("TeacherOne", "Failure voice")
        response = self.dialogue(
            [
                self.utterance(voice_id, "Alice", "First line."),
                self.utterance(voice_id, "Alice", "Again."),
                self.utterance(voice_id, "Alice", "Last line."),
            ]
        )
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]

        self.assertTrue(
            self.worker(FixtureSynthesisIntegration(fail_on_call=2)).run_once()
        )

        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.FAILED)
            self.assertEqual(job.status, JobStatus.FAILED)
        self.assertFalse(self.audio_storage.directory(audio_id).exists())
        self.assertFalse(self.audio_storage.job_directory(job_id).exists())

    def test_cancellation_between_turns_stops_synthesis_and_cleans_segments(
        self,
    ) -> None:
        voice_id = self.create_voice("TeacherOne", "Cancel voice")
        response = self.dialogue(
            [
                self.utterance(voice_id, "Alice", "First line."),
                self.utterance(voice_id, "Bob", "Last line."),
            ]
        )
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]

        def request_cancel(call_number: int) -> None:
            if call_number != 1:
                return
            with self.app.state.session_factory() as session:
                job = session.get(Job, job_id)
                assert job is not None
                job.cancel_requested = True
                session.commit()

        integration = FixtureSynthesisIntegration(after_call=request_cancel)
        self.assertTrue(self.worker(integration).run_once())

        self.assertEqual(len(integration.calls), 1)
        with self.app.state.session_factory() as session:
            audio = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert audio and job
            self.assertEqual(audio.status, AudioStatus.FAILED)
            self.assertEqual(audio.visibility, AudioVisibility.PRIVATE)
            self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertFalse(self.audio_storage.directory(audio_id).exists())
        self.assertFalse(self.audio_storage.job_directory(job_id).exists())

    @staticmethod
    def _peak(samples: tuple[int, ...], start_ms: int, end_ms: int) -> int:
        start = start_ms * 8
        end = end_ms * 8
        return max(abs(value) for value in samples[start:end])


if __name__ == "__main__":
    unittest.main()
