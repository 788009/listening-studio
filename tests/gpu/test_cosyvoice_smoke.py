from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path


GPU_TESTS_ENABLED = os.environ.get("RUN_COSYVOICE_GPU_TESTS") == "1"
if GPU_TESTS_ENABLED:
    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    os.environ["VLLM_NO_USAGE_STATS"] = "1"
    os.environ["VLLM_DO_NOT_TRACK"] = "1"

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request

from backend.app.core.config import Settings
from backend.app.db.models.audio import Audio, AudioStatus
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import Voice, VoiceStatus
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import CosyVoiceAdapter
from backend.app.integrations.identity import ExternalIdentity
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.job_storage import JobStorage
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voice_uploads import (
    VOICE_UPLOAD_JOB_TYPE,
    VoiceUploadService,
)
from backend.app.workers.audio_synthesis import AudioSynthesisJobHandler
from backend.app.workers.jobs import JobWorker
from backend.app.workers.voice_upload import VoiceUploadJobHandler


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OIDC_SUBJECT_HEADER = "X-GPU-Test-OIDC-Subject"
FAILURE_TEXT = "Trigger controlled GPU acceptance cleanup."


class GpuTestIdentityProvider:
    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        subject = request.headers.get(OIDC_SUBJECT_HEADER)
        if not subject:
            return None
        return ExternalIdentity(
            issuer="https://gpu-acceptance.test",
            subject=subject,
        )


class FailureInjectingIntegration:
    def __init__(self, delegate: CosyVoiceAdapter) -> None:
        self.delegate = delegate

    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        return self.delegate.extract_voice(input_audio_path, output_voice_path)

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        if text == FAILURE_TEXT:
            raise RuntimeError("controlled GPU acceptance failure")
        return self.delegate.synthesize(voice_path, text, output_audio_path)


@unittest.skipUnless(
    GPU_TESTS_ENABLED,
    "Set RUN_COSYVOICE_GPU_TESTS=1 to run the CosyVoice GPU acceptance test",
)
class CosyVoiceGpuAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        model_dir_value = os.environ.get("COSYVOICE_MODEL_DIR")
        if not model_dir_value:
            self.fail("COSYVOICE_MODEL_DIR is required")
        self.model_dir = Path(model_dir_value).expanduser().resolve()
        if not self.model_dir.is_dir():
            self.fail(f"CosyVoice model directory is unavailable: {self.model_dir}")

        default_reference = (
            PROJECT_ROOT
            / "voice"
            / "CosyVoice"
            / "asset"
            / "zero_shot_prompt.wav"
        )
        reference_value = os.environ.get("COSYVOICE_SMOKE_INPUT_WAV")
        self.reference_source = (
            Path(reference_value).expanduser().resolve()
            if reference_value
            else default_reference
        )
        if not self.reference_source.is_file():
            self.fail(f"CosyVoice reference WAV is unavailable: {self.reference_source}")

        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'gpu-acceptance.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=False,
            auth_session_secret="gpu-acceptance-session-secret-32-chars",
            cosyvoice_model_dir=self.model_dir,
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
            dialogue_silence_milliseconds=50,
        )
        self.app = create_app(
            self.settings,
            identity_provider=GpuTestIdentityProvider(),
        )
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.job_storage = JobStorage(self.settings.data_dir)
        adapter = CosyVoiceAdapter(self.model_dir)
        self.integration = FailureInjectingIntegration(adapter)
        self.worker = self._worker()

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()
        self.assertFalse(self.root.exists(), "temporary GPU acceptance data was retained")

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

    @staticmethod
    def teacher_headers(request_id: str) -> dict[str, str]:
        return {
            OIDC_SUBJECT_HEADER: "cosyvoice-gpu-acceptance",
            "X-Request-ID": request_id,
        }

    def assert_status(
        self,
        response: httpx.Response,
        expected: int,
        stage: str,
    ) -> None:
        self.assertEqual(
            response.status_code,
            expected,
            f"{stage}: expected HTTP {expected}, got {response.status_code}: {response.text}",
        )

    def _worker(self) -> JobWorker:
        synthesis_service = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=self.integration,
        )
        voice_service = VoiceUploadService(
            storage=self.voice_storage,
            max_upload_bytes=self.settings.max_upload_bytes,
            integration=self.integration,
            job_storage=self.job_storage,
        )
        return JobWorker(
            self.app.state.session_factory,
            {
                VOICE_UPLOAD_JOB_TYPE: VoiceUploadJobHandler(voice_service),
                AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(synthesis_service),
            },
            poll_interval_seconds=0.01,
            job_storage=self.job_storage,
        )

    def normalized_reference_bytes(self) -> bytes:
        import torchaudio

        waveform, sample_rate = torchaudio.load(str(self.reference_source))
        normalized_path = self.root / "reference-pcm16.wav"
        torchaudio.save(
            str(normalized_path),
            waveform,
            sample_rate,
            encoding="PCM_S",
            bits_per_sample=16,
        )
        content = normalized_path.read_bytes()
        normalized_path.unlink()
        return content

    def run_job(self, stage: str) -> float:
        started = time.perf_counter()
        self.assertTrue(self.worker.run_once(), f"{stage}: worker found no queued job")
        return time.perf_counter() - started

    def assert_playable_wav(self, audio_id: int) -> float:
        expected = self.settings.data_dir / "audio" / str(audio_id) / "audio.wav"
        self.assertEqual(self.audio_storage.path(audio_id), expected)
        self.assertTrue(expected.is_file(), f"audio {audio_id} output is missing")
        with wave.open(str(expected), "rb") as audio_file:
            sample_rate = audio_file.getframerate()
            frame_count = audio_file.getnframes()
            self.assertGreater(audio_file.getnchannels(), 0)
            self.assertGreater(audio_file.getsampwidth(), 0)
        self.assertGreater(sample_rate, 0)
        self.assertGreater(frame_count, 0)
        duration = frame_count / sample_rate
        self.assertGreater(duration, 0)
        return duration

    def test_real_worker_voice_single_dialogue_and_cleanup(self) -> None:
        started = time.perf_counter()
        profile_probe = self.send(
            "GET",
            "/api/users/me",
            headers=self.teacher_headers("gpu-first-login"),
        )
        self.assert_status(profile_probe, 200, "create pending GPU test user")
        profile = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.teacher_headers("gpu-complete-profile"),
            json={
                "userId": "GpuAcceptance",
                "username": "GPU Acceptance",
                "locale": "en",
            },
        )
        self.assert_status(profile, 200, "complete GPU test user")
        gender = self.send(
            "POST",
            "/api/voice-tags",
            headers=self.teacher_headers("gpu-create-gender"),
            json={"type": "gender", "value": "female"},
        )
        self.assert_status(gender, 201, "create GPU voice tag")

        upload = self.send(
            "POST",
            "/api/voices",
            headers=self.teacher_headers("gpu-upload-voice"),
            data={
                "title": "GPU acceptance voice",
                "genderTagId": str(gender.json()["id"]),
                "visibility": "private",
            },
            files={
                "file": (
                    "reference.wav",
                    self.normalized_reference_bytes(),
                    "audio/wav",
                )
            },
        )
        self.assert_status(upload, 202, "submit real voice extraction")
        voice_id = upload.json()["voiceId"]
        voice_job_id = upload.json()["jobId"]
        voice_elapsed = self.run_job("real voice extraction")

        expected_voice_directory = self.settings.data_dir / "voice" / str(voice_id)
        self.assertEqual(self.voice_storage.directory(voice_id), expected_voice_directory)
        self.assertTrue(self.voice_storage.exists(voice_id, VoiceAsset.MODEL))
        self.assertTrue(self.voice_storage.exists(voice_id, VoiceAsset.REFERENCE))
        self.assertGreater(
            self.voice_storage.path(voice_id, VoiceAsset.MODEL).stat().st_size,
            0,
        )
        with self.app.state.session_factory() as session:
            voice = session.get(Voice, voice_id)
            voice_job = session.get(Job, voice_job_id)
            self.assertIsNotNone(voice)
            self.assertIsNotNone(voice_job)
            assert voice is not None and voice_job is not None
            self.assertIs(voice.status, VoiceStatus.READY)
            self.assertIs(voice_job.status, JobStatus.SUCCEEDED)

        single = self.send(
            "POST",
            "/api/audios",
            headers=self.teacher_headers("gpu-submit-single"),
            json={
                "title": "GPU single turn",
                "text": "Please open the window.",
                "voiceId": voice_id,
                "visibility": "private",
            },
        )
        dialogue = self.send(
            "POST",
            "/api/audios/dialogues",
            headers=self.teacher_headers("gpu-submit-dialogue"),
            json={
                "title": "GPU two turn dialogue",
                "utterances": [
                    {
                        "voiceId": voice_id,
                        "speakerDisplayName": "Teacher",
                        "text": "Good morning.",
                    },
                    {
                        "voiceId": voice_id,
                        "speakerDisplayName": "Student",
                        "text": "Good morning, teacher.",
                    },
                ],
                "visibility": "private",
            },
        )
        self.assert_status(single, 202, "submit real single-turn synthesis")
        self.assert_status(dialogue, 202, "submit real two-turn synthesis")
        single_audio_id = single.json()["audioId"]
        dialogue_audio_id = dialogue.json()["audioId"]
        single_job_id = single.json()["jobId"]
        dialogue_job_id = dialogue.json()["jobId"]

        with self.app.state.session_factory() as session:
            self.assertIs(session.get(Job, single_job_id).status, JobStatus.QUEUED)
            self.assertIs(session.get(Job, dialogue_job_id).status, JobStatus.QUEUED)
        single_elapsed = self.run_job("real single-turn synthesis")
        with self.app.state.session_factory() as session:
            self.assertIs(session.get(Job, single_job_id).status, JobStatus.SUCCEEDED)
            self.assertIs(session.get(Job, dialogue_job_id).status, JobStatus.QUEUED)
            self.assertIs(session.get(Audio, single_audio_id).status, AudioStatus.READY)
            self.assertIs(session.get(Audio, dialogue_audio_id).status, AudioStatus.PENDING)
        dialogue_elapsed = self.run_job("real two-turn synthesis")
        self.assertFalse(self.worker.run_once(), "unexpected queued GPU job remained")

        single_duration = self.assert_playable_wav(single_audio_id)
        dialogue_duration = self.assert_playable_wav(dialogue_audio_id)
        with self.app.state.session_factory() as session:
            self.assertIs(session.get(Job, dialogue_job_id).status, JobStatus.SUCCEEDED)
            self.assertIs(session.get(Audio, dialogue_audio_id).status, AudioStatus.READY)
        for audio_id in (single_audio_id, dialogue_audio_id):
            playback = self.send(
                "GET",
                f"/media/audio/{audio_id}",
                headers=self.teacher_headers(f"gpu-play-{audio_id}"),
            )
            self.assert_status(playback, 200, f"play generated audio {audio_id}")
            self.assertEqual(playback.headers["content-type"], "audio/wav")

        failed = self.send(
            "POST",
            "/api/audios",
            headers=self.teacher_headers("gpu-submit-controlled-failure"),
            json={
                "title": "GPU cleanup check",
                "text": FAILURE_TEXT,
                "voiceId": voice_id,
                "visibility": "private",
            },
        )
        self.assert_status(failed, 202, "submit controlled failure")
        failed_audio_id = failed.json()["audioId"]
        failed_job_id = failed.json()["jobId"]
        failure_elapsed = self.run_job("controlled failure cleanup")
        with self.app.state.session_factory() as session:
            failed_audio = session.get(Audio, failed_audio_id)
            failed_job = session.get(Job, failed_job_id)
            self.assertIsNotNone(failed_audio)
            self.assertIsNotNone(failed_job)
            assert failed_audio is not None and failed_job is not None
            self.assertIs(failed_audio.status, AudioStatus.FAILED)
            self.assertIs(failed_job.status, JobStatus.FAILED)
            self.assertIn("RuntimeError", failed_audio.error_summary or "")
        self.assertFalse(self.audio_storage.path(failed_audio_id).exists())
        self.assertFalse(self.audio_storage.job_directory(failed_job_id).exists())
        if self.job_storage.root.exists():
            self.assertEqual(list(self.job_storage.root.iterdir()), [])

        log_text = (self.settings.log_dir / "backend.log").read_text(encoding="utf-8")
        for request_id, message in (
            ("gpu-upload-voice", "Voice upload submitted"),
            ("gpu-submit-single", "Audio synthesis submitted"),
            ("gpu-submit-dialogue", "Dialogue synthesis submitted"),
            ("gpu-submit-controlled-failure", "Audio synthesis submitted"),
        ):
            self.assertTrue(
                any(
                    f"request_id={request_id}" in line and message in line
                    for line in log_text.splitlines()
                ),
                f"{message} request log is missing",
            )
        for job_id in (voice_job_id, single_job_id, dialogue_job_id, failed_job_id):
            self.assertIn(f"request_id=job-{job_id} job_id={job_id}", log_text)
        self.assertIn(f"Job failed job_id={failed_job_id}", log_text)
        self.assertNotIn(FAILURE_TEXT, log_text)

        for audio_id in (failed_audio_id, dialogue_audio_id, single_audio_id):
            deleted = self.send(
                "DELETE",
                f"/api/audios/{audio_id}",
                headers=self.teacher_headers(f"gpu-delete-audio-{audio_id}"),
            )
            self.assert_status(deleted, 204, f"delete GPU audio {audio_id}")
            self.assertFalse(self.audio_storage.directory(audio_id).exists())
        deleted_voice = self.send(
            "DELETE",
            f"/api/voices/{voice_id}",
            headers=self.teacher_headers("gpu-delete-voice"),
        )
        self.assert_status(deleted_voice, 204, "delete GPU voice")
        self.assertFalse(self.voice_storage.directory(voice_id).exists())
        with self.app.state.session_factory() as session:
            self.assertIsNone(session.get(Voice, voice_id))
            for audio_id in (single_audio_id, dialogue_audio_id, failed_audio_id):
                self.assertIsNone(session.get(Audio, audio_id))

        integration_path = PROJECT_ROOT / "backend" / "app" / "integrations" / "cosyvoice.py"
        for source_path in (PROJECT_ROOT / "backend" / "app").rglob("*.py"):
            if source_path == integration_path:
                continue
            self.assertNotIn(
                "voice.CosyVoice.modules",
                source_path.read_text(encoding="utf-8"),
                f"CosyVoice was imported outside its adapter: {source_path}",
            )

        total_elapsed = time.perf_counter() - started
        print(
            "\nGPU acceptance timings: "
            f"voice={voice_elapsed:.3f}s "
            f"single={single_elapsed:.3f}s "
            f"dialogue={dialogue_elapsed:.3f}s "
            f"failure={failure_elapsed:.3f}s "
            f"single_wav={single_duration:.3f}s "
            f"dialogue_wav={dialogue_duration:.3f}s "
            f"total={total_elapsed:.3f}s"
        )


if __name__ == "__main__":
    unittest.main()
