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

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.paper import Paper, PaperItem, PaperStatus
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService
from backend.app.services.paper_renderer import PaperAudioRenderer
from backend.app.services.paper_rendering import (
    PAPER_RENDER_JOB_TYPE,
    PaperRenderService,
)
from backend.app.workers.jobs import JobWorker
from backend.app.workers.paper_rendering import PaperRenderJobHandler


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FailingRenderer(PaperAudioRenderer):
    def render(self, *args: object, **kwargs: object) -> Path:
        raise RuntimeError("fixture rendering failed")


class CancellingRenderer(PaperAudioRenderer):
    def __init__(self, cancel: Callable[[], None]) -> None:
        self.cancel = cancel

    def render(
        self,
        source_paths: list[Path],
        output_path: Path,
        **kwargs: int,
    ) -> Path:
        del source_paths, kwargs
        PaperRenderingIntegrationTest.write_wav(output_path, 100, 1000)
        self.cancel()
        return output_path


class PaperRenderingIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'paper-rendering.sqlite3'}"
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
        self.profile("first", "TeacherOne")

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
    def write_wav(
        path: Path,
        duration_milliseconds: int,
        amplitude: int,
        *,
        sample_rate: int = 8000,
        channels: int = 1,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = sample_rate * duration_milliseconds // 1000
        frames = struct.pack("<h", amplitude) * frame_count * channels
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(channels)
            audio_file.setsampwidth(2)
            audio_file.setframerate(sample_rate)
            audio_file.writeframes(frames)

    def ready_audio(
        self,
        title: str,
        text: str,
        duration_milliseconds: int,
        amplitude: int,
        *,
        sample_rate: int = 8000,
        channels: int = 1,
    ) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, "TeacherOne")
            assert user is not None
            service = AudioService(self.storage)
            audio = service.create_audio(
                session,
                author=user,
                title=title,
                source_type=AudioSourceType.CORPUS,
                text=text,
            )
            service.transition_status(session, audio, AudioStatus.PROCESSING)
            self.write_wav(
                self.storage.path(audio.id),
                duration_milliseconds,
                amplitude,
                sample_rate=sample_rate,
                channels=channels,
            )
            service.record_file_metadata(session, audio)
            service.transition_status(session, audio, AudioStatus.READY)
            service.set_visibility(session, audio, AudioVisibility.PRIVATE)
            session.commit()
            return audio.id

    def create_paper(self, audio_ids: list[int]) -> int:
        preset = self.send(
            "POST",
            "/api/paper-presets",
            headers=self.headers(),
            json={
                "name": "Fixture preset",
                "introSilenceMilliseconds": 50,
                "interItemSilenceMilliseconds": 75,
                "repeatCount": 2,
                "outroSilenceMilliseconds": 25,
            },
        )
        self.assertEqual(preset.status_code, 201, preset.text)
        paper = self.send(
            "POST",
            "/api/papers",
            headers=self.headers(),
            json={
                "title": "Fixture paper",
                "presetId": preset.json()["id"],
                "audioIds": audio_ids,
            },
        )
        self.assertEqual(paper.status_code, 201, paper.text)
        return paper.json()["id"]

    def submit(self, paper_id: int) -> httpx.Response:
        return self.send(
            "POST",
            f"/api/papers/{paper_id}/render",
            headers=self.headers(),
        )

    def worker(
        self,
        renderer: PaperAudioRenderer | None = None,
    ) -> JobWorker:
        service = PaperRenderService(self.storage, renderer=renderer)
        return JobWorker(
            self.app.state.session_factory,
            {PAPER_RENDER_JOB_TYPE: PaperRenderJobHandler(service)},
            poll_interval_seconds=0.01,
        )

    def test_render_preserves_order_repeats_sources_and_records_metadata(self) -> None:
        first_id = self.ready_audio("First source", "First text.", 100, 1000)
        second_id = self.ready_audio(
            "Second source",
            "Second text.",
            200,
            3000,
            sample_rate=16000,
            channels=2,
        )
        paper_id = self.create_paper([first_id, second_id])

        response = self.submit(paper_id)

        self.assertEqual(response.status_code, 202, response.text)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        self.assertEqual(response.json()["paperId"], paper_id)
        self.assertEqual(self.submit(paper_id).status_code, 409)
        with self.app.state.session_factory() as session:
            output = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert output and job
            self.assertEqual(output.source_type, AudioSourceType.ASSEMBLY)
            self.assertEqual(output.visibility, AudioVisibility.PRIVATE)
            self.assertEqual(
                output.text,
                "1. First source\nFirst text.\n\n2. Second source\nSecond text.",
            )
            self.assertEqual(
                job.input_summary, {"paperId": paper_id, "audioId": audio_id}
            )

        self.assertTrue(self.worker().run_once())

        with wave.open(str(self.storage.path(audio_id)), "rb") as audio_file:
            self.assertEqual(audio_file.getframerate(), 8000)
            self.assertEqual(audio_file.getnchannels(), 1)
            self.assertEqual(audio_file.getsampwidth(), 2)
            frame_count = audio_file.getnframes()
            samples = struct.unpack(
                f"<{frame_count}h",
                audio_file.readframes(frame_count),
            )
        self.assertAlmostEqual(frame_count / 8000, 0.75, delta=0.01)
        self.assertEqual(self._peak(samples, 0, 40), 0)
        self.assertGreater(self._peak(samples, 60, 240), 0)
        self.assertEqual(self._peak(samples, 260, 310), 0)
        self.assertGreater(self._peak(samples, 340, 710), 2000)
        self.assertEqual(self._peak(samples, 730, 750), 0)

        with self.app.state.session_factory() as session:
            paper = session.get(Paper, paper_id)
            output = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            sources = [session.get(Audio, value) for value in (first_id, second_id)]
            assert paper and output and job and all(sources)
            self.assertEqual(paper.status, PaperStatus.READY)
            self.assertEqual(output.status, AudioStatus.READY)
            self.assertAlmostEqual(output.duration_seconds or 0, 0.75, delta=0.01)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(job.result_type, "audio")
            self.assertEqual(job.result_id, audio_id)
            self.assertEqual(
                [item.audio_id for item in paper.items], [first_id, second_id]
            )
            self.assertTrue(all(item.status is AudioStatus.READY for item in sources))
        self.assertFalse(self.storage.job_directory(job_id).exists())

    def test_source_status_change_before_start_fails_without_modifying_items(
        self,
    ) -> None:
        source_id = self.ready_audio("Changing source", "Text.", 100, 1000)
        paper_id = self.create_paper([source_id])
        response = self.submit(paper_id)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        with self.app.state.session_factory() as session:
            source = session.get(Audio, source_id)
            assert source is not None
            source.status = AudioStatus.PROCESSING
            session.commit()

        self.assertTrue(self.worker().run_once())

        with self.app.state.session_factory() as session:
            paper = session.get(Paper, paper_id)
            output = session.get(Audio, audio_id)
            source = session.get(Audio, source_id)
            job = session.get(Job, job_id)
            items = list(session.query(PaperItem).filter_by(paper_id=paper_id))
            assert paper and output and source and job
            self.assertEqual(paper.status, PaperStatus.FAILED)
            self.assertEqual(output.status, AudioStatus.FAILED)
            self.assertEqual(source.status, AudioStatus.PROCESSING)
            self.assertEqual([item.audio_id for item in items], [source_id])
            self.assertEqual(job.status, JobStatus.FAILED)
        self.assertTrue(self.storage.path(source_id).is_file())
        self.assertFalse(self.storage.directory(audio_id).exists())
        self.assertFalse(self.storage.job_directory(job_id).exists())

    def test_cancellation_cleans_render_files_and_preserves_sources(self) -> None:
        source_id = self.ready_audio("Cancel source", "Text.", 100, 1000)
        paper_id = self.create_paper([source_id])
        response = self.submit(paper_id)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]

        def cancel() -> None:
            with self.app.state.session_factory() as session:
                job = session.get(Job, job_id)
                assert job is not None
                job.cancel_requested = True
                session.commit()

        self.assertTrue(self.worker(CancellingRenderer(cancel)).run_once())

        with self.app.state.session_factory() as session:
            paper = session.get(Paper, paper_id)
            output = session.get(Audio, audio_id)
            source = session.get(Audio, source_id)
            job = session.get(Job, job_id)
            assert paper and output and source and job
            self.assertEqual(paper.status, PaperStatus.FAILED)
            self.assertEqual(output.status, AudioStatus.FAILED)
            self.assertEqual(source.status, AudioStatus.READY)
            self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertTrue(self.storage.path(source_id).is_file())
        self.assertFalse(self.storage.directory(audio_id).exists())
        self.assertFalse(self.storage.job_directory(job_id).exists())

    def test_retry_uses_atomically_written_output(self) -> None:
        source_id = self.ready_audio("Retry source", "Text.", 100, 1000)
        paper_id = self.create_paper([source_id])
        response = self.submit(paper_id)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        self.write_wav(self.storage.path(audio_id), 320, 2000)

        self.assertTrue(self.worker(FailingRenderer()).run_once())

        with self.app.state.session_factory() as session:
            paper = session.get(Paper, paper_id)
            output = session.get(Audio, audio_id)
            job = session.get(Job, job_id)
            assert paper and output and job
            self.assertEqual(paper.status, PaperStatus.READY)
            self.assertEqual(output.status, AudioStatus.READY)
            self.assertAlmostEqual(output.duration_seconds or 0, 0.32)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertFalse(self.storage.job_directory(job_id).exists())

    @staticmethod
    def _peak(samples: tuple[int, ...], start_ms: int, end_ms: int) -> int:
        start = start_ms * 8
        end = end_ms * 8
        return max((abs(value) for value in samples[start:end]), default=0)


if __name__ == "__main__":
    unittest.main()
