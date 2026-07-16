from __future__ import annotations

import io
import json
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path

from alembic import command
from alembic.config import Config

from backend.app.consistency import main as consistency_main
from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchStatus,
)
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)
from backend.app.factory import create_app
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.consistency import ConsistencyService
from backend.app.services.job_storage import JobStorage
from backend.app.services.jobs import JobService
from backend.app.services.users import UserService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConsistencyIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'consistency.sqlite3'}"
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
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.job_storage = JobStorage(self.settings.data_dir)
        self.ids = self._create_inconsistent_fixture()

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    def _create_inconsistent_fixture(self) -> dict[str, int]:
        with self.app.state.session_factory() as session:
            user_service = UserService()
            owner = user_service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="consistency-owner",
            )
            user_service.set_user_id(session, owner, "ConsistencyOwner")
            voice = Voice(
                author=owner,
                title="Missing voice",
                normalized_title="missing voice",
                status=VoiceStatus.READY,
                visibility=VoiceVisibility.PUBLIC,
                sample_source=VoiceSampleSource.ORIGINAL,
            )
            audio = Audio(
                author=owner,
                title="Metadata mismatch",
                normalized_title="metadata mismatch",
                text="Audio text",
                source_type=AudioSourceType.SINGLE_SPEAKER,
                status=AudioStatus.READY,
                visibility=AudioVisibility.PUBLIC,
            )
            session.add_all([voice, audio])
            session.flush()

            retryable = JobService().create_job(
                session,
                owner=owner,
                job_type="retryable_task",
                input_summary={"title": "Retryable"},
                retryable=True,
            )
            unsafe = JobService().create_job(
                session,
                owner=owner,
                job_type="unsafe_task",
                input_summary={"title": "Unsafe"},
            )
            terminal = JobService().create_job(
                session,
                owner=owner,
                job_type="finished_task",
                input_summary={"title": "Finished"},
            )
            batch_job = JobService().create_job(
                session,
                owner=owner,
                job_type="corpus_generation",
                input_summary={"batchId": 1},
                retryable=True,
            )
            active_audio = Audio(
                author=owner,
                title="Active batch audio",
                normalized_title="active batch audio",
                text="Pending audio text",
                source_type=AudioSourceType.CORPUS,
                status=AudioStatus.PROCESSING,
                visibility=AudioVisibility.PRIVATE,
            )
            batch = GenerationBatch(
                owner=owner,
                job=batch_job,
                question_types=["multiple_choice"],
                requested_count=1,
                status=GenerationBatchStatus.PROCESSING,
            )
            session.add_all([active_audio, batch])
            session.flush()
            batch_job.input_summary = {"batchId": batch.id}
            session.add(
                GenerationBatchItem(
                    batch=batch,
                    position=0,
                    status=GenerationBatchStatus.PROCESSING,
                    audio=active_audio,
                )
            )
            retryable.status = JobStatus.RUNNING
            retryable.progress = 30
            unsafe.status = JobStatus.RUNNING
            unsafe.progress = 40
            terminal.status = JobStatus.SUCCEEDED
            terminal.progress = 100
            session.commit()
            ids = {
                "voice": voice.id,
                "audio": audio.id,
                "retryable": retryable.id,
                "unsafe": unsafe.id,
                "terminal": terminal.id,
                "active_audio": active_audio.id,
            }

        temporary_voice = self.voice_storage.create_temporary_file(
            ids["voice"],
            VoiceAsset.MODEL,
        )
        temporary_voice.write_bytes(b"incomplete model")
        unknown_voice_file = self.voice_storage.directory(ids["voice"]) / "notes.txt"
        unknown_voice_file.write_text("keep", encoding="utf-8")
        audio_path = self.audio_storage.path(ids["audio"])
        self.audio_storage.prepare_directory(ids["audio"])
        self._write_wav(audio_path)
        for job_id in (ids["retryable"], ids["unsafe"], ids["terminal"]):
            directory = self.job_storage.directory(job_id)
            directory.mkdir(parents=True)
            (directory / "temporary.bin").write_bytes(b"temporary")

        (self.voice_storage.root / "999").mkdir(parents=True)
        (self.voice_storage.root / "unknown-directory").mkdir()
        (self.audio_storage.job_root / "999").mkdir(parents=True)
        staged = self.voice_storage.root / ".deleting-777"
        staged.mkdir()
        (staged / "voice.pt").write_bytes(b"staged")
        return ids

    @staticmethod
    def _write_wav(path: Path) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"\x00\x00" * 800)

    def _database_state(self) -> dict[str, object]:
        with self.app.state.session_factory() as session:
            voice = session.get(Voice, self.ids["voice"])
            audio = session.get(Audio, self.ids["audio"])
            jobs = {
                name: session.get(Job, self.ids[name])
                for name in ("retryable", "unsafe", "terminal")
            }
            assert voice is not None and audio is not None
            active_audio = session.get(Audio, self.ids["active_audio"])
            assert active_audio is not None
            assert all(job is not None for job in jobs.values())
            return {
                "voice": (voice.status, voice.visibility, voice.error_summary),
                "audio": (
                    audio.status,
                    audio.audio_format,
                    audio.duration_seconds,
                    audio.file_size_bytes,
                ),
                "active_audio": active_audio.status,
                "jobs": {name: job.status for name, job in jobs.items() if job},
            }

    def _data_entries(self) -> set[str]:
        return {
            str(path.relative_to(self.settings.data_dir))
            for path in self.settings.data_dir.rglob("*")
        }

    def test_dry_run_reports_without_modifying_database_or_files(self) -> None:
        database_before = self._database_state()
        files_before = self._data_entries()
        with self.app.state.session_factory() as session:
            report = ConsistencyService(self.settings.data_dir).run(session)

        self.assertEqual(report.mode, "dry-run")
        self.assertEqual(database_before, self._database_state())
        self.assertEqual(files_before, self._data_entries())
        self.assertTrue(
            {"missing_file", "orphan_directory", "legacy_temporary", "dangling_job"}
            <= {issue.code for issue in report.issues}
        )
        self.assertTrue(all(issue.result == "reported" for issue in report.issues))

        output = io.StringIO()
        with redirect_stdout(output):
            result = consistency_main([], settings=self.settings)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "dry-run")
        self.assertEqual(database_before, self._database_state())
        self.assertEqual(files_before, self._data_entries())

    def test_apply_is_idempotent_and_preserves_unknown_directories(self) -> None:
        with self.app.state.session_factory() as session:
            first = ConsistencyService(self.settings.data_dir).run(session, apply=True)

        state = self._database_state()
        self.assertEqual(state["voice"][0], VoiceStatus.FAILED)
        self.assertEqual(state["voice"][1], VoiceVisibility.PRIVATE)
        self.assertEqual(state["audio"][0], AudioStatus.READY)
        self.assertEqual(state["audio"][1], "wav")
        self.assertAlmostEqual(state["audio"][2], 0.1)
        self.assertGreater(state["audio"][3], 0)
        self.assertEqual(state["active_audio"], AudioStatus.PROCESSING)
        self.assertEqual(state["jobs"]["retryable"], JobStatus.QUEUED)
        self.assertEqual(state["jobs"]["unsafe"], JobStatus.FAILED)
        self.assertEqual(state["jobs"]["terminal"], JobStatus.SUCCEEDED)
        self.assertFalse(self.job_storage.directory(self.ids["unsafe"]).exists())
        self.assertFalse(self.job_storage.directory(self.ids["terminal"]).exists())
        self.assertTrue(self.job_storage.directory(self.ids["retryable"]).exists())
        self.assertFalse((self.voice_storage.root / ".deleting-777").exists())
        self.assertFalse(
            any(
                path.name.startswith(".voice.pt.")
                for path in self.voice_storage.directory(self.ids["voice"]).iterdir()
            )
        )
        self.assertEqual(
            (self.voice_storage.directory(self.ids["voice"]) / "notes.txt").read_text(
                encoding="utf-8"
            ),
            "keep",
        )
        for path in (
            self.voice_storage.root / "999",
            self.voice_storage.root / "unknown-directory",
            self.audio_storage.job_root / "999",
        ):
            self.assertTrue(path.is_dir())

        first_summary = first.to_dict()["summary"]
        self.assertGreater(first_summary["repaired"], 0)
        with self.app.state.session_factory() as session:
            second = ConsistencyService(self.settings.data_dir).run(session, apply=True)
        self.assertEqual(second.to_dict()["summary"]["repaired"], 0)
        self.assertTrue(
            all(
                issue.code in {"orphan_directory", "unknown_file"}
                for issue in second.issues
            )
        )


if __name__ == "__main__":
    unittest.main()
