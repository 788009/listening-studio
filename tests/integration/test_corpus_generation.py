from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.models.audio import Audio, AudioSourceType, AudioStatus
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchStatus,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.integrations.llm import (
    ListeningGenerationRequest,
    PlaceholderListeningContentGenerator,
    ValidatingListeningContentGenerator,
)
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import CORPUS_GENERATION_JOB_TYPE
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService
from backend.app.workers.corpus_generation import CorpusGenerationJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CountingGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[ListeningGenerationRequest, str]] = []
        self.implementation = PlaceholderListeningContentGenerator()

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> object:
        self.calls.append((request, call_id))
        return self.implementation.generate(request, call_id=call_id)


class FailOnceSynthesisIntegration:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[tuple[Path, str, Path]] = []

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        self.calls.append((Path(voice_path), text, Path(output_audio_path)))
        if self.fail_on_call == len(self.calls):
            self.fail_on_call = None
            raise RuntimeError("fixture synthesis failure")
        with wave.open(str(output_audio_path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 800)
        return Path(output_audio_path)

    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        raise AssertionError("Voice extraction is not expected")


class CorpusGenerationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'corpus-generation.sqlite3'}"
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
            dialogue_silence_milliseconds=25,
        )
        self.app = create_app(self.settings)
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.complete_profile()
        self.host_voice = self.create_voice("Host voice")
        self.guest_voice = self.create_voice("Guest voice")
        with self.app.state.session_factory() as session:
            tag = AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="bulk_topic",
            )
            session.commit()
            self.bulk_tag_id = tag.id

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
            user = UserRepository().get_by_user_id(session, "TeacherOne")
            assert user is not None
            service = VoiceService(self.voice_storage)
            voice = service.create_voice(session, author=user, title=title)
            service.transition_status(session, voice, VoiceStatus.PROCESSING)
            self.voice_storage.path(voice.id, VoiceAsset.MODEL).write_bytes(b"voice")
            service.transition_status(session, voice, VoiceStatus.READY)
            session.commit()
            return voice.id

    def submit_batch(self, *, include_guest: bool = True) -> tuple[int, int]:
        mapping = {"Host": self.host_voice}
        if include_guest:
            mapping["Guest"] = self.guest_voice
        response = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers(),
            files=[
                ("questionTypes", (None, "multiple_choice")),
                ("count", (None, "2")),
                ("corpus", (None, "A corpus for two listening exercises.")),
                ("tagIds", (None, str(self.bulk_tag_id))),
                ("speakerVoiceMap", (None, json.dumps(mapping))),
            ],
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["batchId"], response.json()["jobId"]

    def worker(
        self,
        generator: CountingGenerator,
        integration: FailOnceSynthesisIntegration,
    ) -> JobWorker:
        synthesis_service = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=integration,
        )
        service = CorpusGenerationService(
            generator=ValidatingListeningContentGenerator(generator),
            corpus_storage=CorpusStorage(self.settings.data_dir),
            synthesis_service=synthesis_service,
            voice_storage=self.voice_storage,
            silence_milliseconds=self.settings.dialogue_silence_milliseconds,
        )
        return JobWorker(
            self.app.state.session_factory,
            {CORPUS_GENERATION_JOB_TYPE: CorpusGenerationJobHandler(service)},
            poll_interval_seconds=0.01,
        )

    def test_generates_items_with_mappings_text_types_and_merged_tags(self) -> None:
        batch_id, job_id = self.submit_batch()
        generator = CountingGenerator()
        integration = FailOnceSynthesisIntegration()

        self.assertTrue(self.worker(generator, integration).run_once())

        self.assertEqual(len(generator.calls), 1)
        self.assertEqual(len(integration.calls), 4)
        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            job = session.get(Job, job_id)
            assert batch is not None and job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.COMPLETED)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(job.result_type, "generation_batch")
            self.assertEqual(job.result_id, batch.id)
            self.assertEqual(len(batch.items), 2)
            self.assertEqual(
                [item.status for item in batch.items],
                [GenerationBatchStatus.COMPLETED] * 2,
            )
            self.assertEqual([item.attempt_count for item in batch.items], [1, 1])
            audio_ids = [item.audio_id for item in batch.items]
            self.assertTrue(all(audio_id is not None for audio_id in audio_ids))
            audios = [session.get(Audio, audio_id) for audio_id in audio_ids]
            self.assertTrue(all(audio is not None for audio in audios))
            ready = [audio for audio in audios if audio is not None]
            self.assertEqual(
                [audio.title for audio in ready],
                ["Listening Practice 1", "Listening Practice 2"],
            )
            self.assertTrue(
                all(audio.source_type is AudioSourceType.CORPUS for audio in ready)
            )
            self.assertTrue(all(audio.status is AudioStatus.READY for audio in ready))
            expected_text = (
                "Host: Welcome to today's listening practice.\n"
                "Guest: Clear communication helps learners understand new ideas."
            )
            self.assertEqual([audio.text for audio in ready], [expected_text] * 2)
            for audio in ready:
                self.assertEqual(
                    [turn.voice_id for turn in audio.utterances],
                    [self.host_voice, self.guest_voice],
                )
                self.assertEqual(
                    {(tag.type, tag.value) for tag in audio.tags},
                    {
                        (AudioTagType.AUTHOR, "TeacherOne"),
                        (AudioTagType.TOPIC, "bulk_topic"),
                        (AudioTagType.TOPIC, "education"),
                        (AudioTagType.CATEGORY, "listening_practice"),
                        (AudioTagType.SPEAKER, "Host_voice"),
                        (AudioTagType.SPEAKER, "Guest_voice"),
                    },
                )
            self.assertEqual(
                [item.generated_content["question_types"] for item in batch.items],
                [["multiple_choice"], ["multiple_choice"]],
            )
        self.assertFalse((self.root / "data" / "jobs" / str(job_id)).exists())

        detail = self.send(
            "GET",
            f"/api/generation-batches/{batch_id}",
            headers=self.headers(),
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [item["questionTypes"] for item in detail.json()["items"]],
            [["multiple_choice"], ["multiple_choice"]],
        )
        bulk_update = self.send(
            "PATCH",
            f"/api/generation-batches/{batch_id}/completed-audios",
            headers=self.headers(),
            json={"tagIds": [self.bulk_tag_id], "visibility": "public"},
        )
        self.assertEqual(bulk_update.status_code, 200, bulk_update.text)
        self.assertEqual(bulk_update.json()["updatedCount"], 2)
        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            assert batch is not None
            for item in batch.items:
                assert item.audio is not None
                self.assertEqual(item.audio.visibility.value, "public")
                self.assertEqual(
                    {(tag.type, tag.value) for tag in item.audio.tags},
                    {
                        (AudioTagType.AUTHOR, "TeacherOne"),
                        (AudioTagType.TOPIC, "bulk_topic"),
                        (AudioTagType.SPEAKER, "Host_voice"),
                        (AudioTagType.SPEAKER, "Guest_voice"),
                    },
                )
        delete_mapping_voice = self.send(
            "DELETE",
            f"/api/voices/{self.host_voice}",
            headers=self.headers(),
        )
        self.assertEqual(delete_mapping_voice.status_code, 409)
        self.assertEqual(
            delete_mapping_voice.json()["error"]["details"][
                "batchVoiceMappingCount"
            ],
            1,
        )
        result_audio_id = detail.json()["items"][0]["audioId"]
        delete_result_audio = self.send(
            "DELETE",
            f"/api/audios/{result_audio_id}",
            headers=self.headers(),
        )
        self.assertEqual(delete_result_audio.status_code, 409)
        self.assertEqual(
            delete_result_audio.json()["error"]["details"]["batchItemCount"],
            1,
        )

    def test_missing_mapping_fails_batch_before_synthesis(self) -> None:
        batch_id, job_id = self.submit_batch(include_guest=False)
        generator = CountingGenerator()
        integration = FailOnceSynthesisIntegration()

        self.assertTrue(self.worker(generator, integration).run_once())

        self.assertEqual(len(generator.calls), 1)
        self.assertEqual(integration.calls, [])
        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            job = session.get(Job, job_id)
            assert batch is not None and job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.FAILED)
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertTrue(
                all(
                    item.status is GenerationBatchStatus.FAILED
                    and item.audio_id is None
                    for item in batch.items
                )
            )
        self.assertFalse((self.root / "data" / "jobs" / str(job_id)).exists())

    def test_failed_item_retry_does_not_repeat_llm_or_successful_audio(self) -> None:
        batch_id, first_job_id = self.submit_batch()
        generator = CountingGenerator()
        integration = FailOnceSynthesisIntegration(fail_on_call=3)
        worker = self.worker(generator, integration)

        self.assertTrue(worker.run_once())

        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            first_job = session.get(Job, first_job_id)
            assert batch is not None and first_job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.FAILED)
            self.assertEqual(first_job.status, JobStatus.SUCCEEDED)
            self.assertEqual(
                [item.status for item in batch.items],
                [GenerationBatchStatus.COMPLETED, GenerationBatchStatus.FAILED],
            )
            successful_audio_id = batch.items[0].audio_id
            failed_audio_id = batch.items[1].audio_id
            failed_item_id = batch.items[1].id
            self.assertIsNotNone(successful_audio_id)
            self.assertIsNotNone(failed_audio_id)

        retry = self.send(
            "POST",
            f"/api/generation-batches/{batch_id}/items/{failed_item_id}/retry",
            headers=self.headers(),
        )
        self.assertEqual(retry.status_code, 202, retry.text)
        retry_job_id = retry.json()["jobId"]
        self.assertTrue(worker.run_once())

        self.assertEqual(len(generator.calls), 1)
        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            retry_job = session.get(Job, retry_job_id)
            assert batch is not None and retry_job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.COMPLETED)
            self.assertEqual(retry_job.status, JobStatus.SUCCEEDED)
            self.assertEqual(
                [item.status for item in batch.items],
                [GenerationBatchStatus.COMPLETED, GenerationBatchStatus.COMPLETED],
            )
            self.assertEqual(batch.items[0].audio_id, successful_audio_id)
            self.assertEqual(batch.items[0].attempt_count, 1)
            self.assertEqual(batch.items[1].attempt_count, 2)
            retried_audio = session.get(Audio, batch.items[1].audio_id)
            assert retried_audio is not None
            self.assertEqual(retried_audio.status, AudioStatus.READY)
            audio_count = session.scalar(select(func.count()).select_from(Audio))
            self.assertEqual(audio_count, 2)


if __name__ == "__main__":
    unittest.main()
