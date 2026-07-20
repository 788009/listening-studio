from __future__ import annotations

import asyncio
import json
import random
import tempfile
import unittest
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models.audio import Audio, AudioSourceType
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.generation_batch import GenerationBatch, GenerationBatchStatus
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import VoiceStatus
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.integrations.llm import (
    PlaceholderListeningContentGenerator,
    PlaceholderTopicTagSuggester,
    ListeningGenerationRequest,
    ListeningGenerationResult,
    ValidatingListeningContentGenerator,
    ValidatingTopicTagSuggester,
)
from backend.app.repositories.users import UserRepository
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import CORPUS_GENERATION_JOB_TYPE
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voice_tags import VoiceTagService
from backend.app.services.voices import VoiceService
from backend.app.workers.corpus_generation import CorpusGenerationJobHandler
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DuplicateTitleGenerator:
    def __init__(self) -> None:
        self.delegate = PlaceholderListeningContentGenerator()

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> ListeningGenerationResult:
        result = self.delegate.generate(request, call_id=call_id)
        items = list(result.items)
        items[1] = items[1].model_copy(
            update={"title": "Ｆinding a Parking Space"}
        )
        return result.model_copy(update={"items": items})


class CorpusGenerationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'generation.sqlite3'}"
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
        self.complete_profile()
        with self.app.state.session_factory() as session:
            male = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="male",
            )
            female = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="female",
            )
            AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="travel",
            )
            AudioTagService().create_user_tag(
                session,
                tag_type=AudioTagType.CATEGORY,
                english_value="short",
            )
            session.commit()
            self.male_voice = self.create_voice(session, "Male voice", male)
            self.female_voice = self.create_voice(session, "Female voice", female)
            session.commit()

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

    def create_voice(self, session: Session, title: str, gender: VoiceTag) -> int:
        owner = UserRepository().get_by_user_id(session, "TeacherOne")
        assert owner is not None
        service = VoiceService(self.voice_storage)
        voice = service.create_voice(session, author=owner, title=title)
        service.replace_gender_tags(session, voice, [gender])
        service.transition_status(session, voice, VoiceStatus.PROCESSING)
        self.voice_storage.path(voice.id, VoiceAsset.MODEL).write_bytes(b"voice")
        service.transition_status(session, voice, VoiceStatus.READY)
        return voice.id

    def test_worker_returns_drafts_with_speakers_topics_and_type_categories(self) -> None:
        response = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.headers(),
            files=[
                (
                    "questionTypeCounts",
                    (
                        None,
                        json.dumps(
                            {
                                "short_dialogue": 2,
                                "long_dialogue": 1,
                                "monologue": 1,
                            }
                        ),
                    ),
                ),
                ("corpus", (None, "A source corpus about a journey.")),
                (
                    "speakerVoiceMap",
                    (
                        None,
                        json.dumps(
                            {
                                "Woman speaker": self.female_voice,
                                "Man speaker": self.male_voice,
                            }
                        ),
                    ),
                ),
            ],
        )
        self.assertEqual(response.status_code, 202, response.text)
        batch_id = response.json()["batchId"]
        job_id = response.json()["jobId"]
        with self.app.state.session_factory() as session:
            owner = UserRepository().get_by_user_id(session, "TeacherOne")
            assert owner is not None
            session.add_all(
                [
                    Audio(
                        author=owner,
                        title=title,
                        normalized_title=title.casefold(),
                        text="Existing audio",
                        source_type=AudioSourceType.CORPUS,
                    )
                    for title in (
                        "Finding a Parking Space",
                        "Finding a Parking Space 2",
                    )
                ]
            )
            session.commit()
        service = CorpusGenerationService(
            generator=ValidatingListeningContentGenerator(
                DuplicateTitleGenerator()
            ),
            tag_suggester=ValidatingTopicTagSuggester(
                PlaceholderTopicTagSuggester(random.Random(1))
            ),
            corpus_storage=CorpusStorage(self.settings.data_dir),
        )
        worker = JobWorker(
            self.app.state.session_factory,
            {CORPUS_GENERATION_JOB_TYPE: CorpusGenerationJobHandler(service)},
            poll_interval_seconds=0.01,
        )
        self.assertTrue(worker.run_once())

        with self.app.state.session_factory() as session:
            batch = session.get(GenerationBatch, batch_id)
            job = session.get(Job, job_id)
            assert batch is not None and job is not None
            self.assertEqual(batch.status, GenerationBatchStatus.COMPLETED)
            self.assertEqual(job.status, JobStatus.SUCCEEDED)
            self.assertEqual(len(batch.items), 4)
            self.assertEqual(session.query(Audio).count(), 2)
            self.assertEqual(
                [(tag.type, tag.value) for tag in batch.tags],
                [
                    (AudioTagType.TOPIC, "travel"),
                    (AudioTagType.CATEGORY, "short"),
                    (AudioTagType.CATEGORY, "long"),
                    (AudioTagType.CATEGORY, "monologue"),
                ],
            )
            self.assertEqual(
                {
                    tag.value: {
                        translation.language: translation.value
                        for translation in tag.translations
                    }
                    for tag in batch.tags
                    if tag.type is AudioTagType.CATEGORY
                },
                {
                    "short": {"zh-CN": "短对话"},
                    "long": {"zh-CN": "长对话"},
                    "monologue": {"zh-CN": "独白"},
                },
            )
            first = batch.items[0].generated_content
            second = batch.items[1].generated_content
            assert first is not None and second is not None
            self.assertEqual(first["question_type"], "short_dialogue")
            self.assertEqual(first["title"], "Finding a Parking Space 3")
            self.assertEqual(second["title"], "Finding a Parking Space 4")
            utterances = first["utterances"]
            assert isinstance(utterances, list)
            self.assertEqual(utterances[0]["speaker_display_name"], "Man speaker")
            self.assertEqual(utterances[0]["voice_id"], self.male_voice)
            self.assertEqual(utterances[1]["speaker_display_name"], "Woman speaker")
            self.assertEqual(utterances[1]["voice_id"], self.female_voice)

        detail = self.send(
            "GET",
            f"/api/generation-batches/{batch_id}",
            headers=self.headers(),
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        payload = detail.json()
        self.assertEqual(payload["progress"], 100)
        self.assertEqual(
            payload["questionTypeCounts"],
            {"short_dialogue": 2, "long_dialogue": 1, "monologue": 1},
        )
        self.assertEqual(
            [(tag["type"], tag["englishValue"]) for tag in payload["tags"]],
            [
                ("topic", "travel"),
                ("category", "short"),
                ("category", "long"),
                ("category", "monologue"),
            ],
        )
        localized_tags = self.send(
            "GET",
            "/api/audio-tags?type=category&language=zh-CN",
            headers=self.headers(),
        )
        self.assertEqual(localized_tags.status_code, 200, localized_tags.text)
        self.assertEqual(
            {
                tag["englishValue"]: tag["displayValue"]
                for tag in localized_tags.json()
            },
            {"short": "短对话", "long": "长对话", "monologue": "独白"},
        )
        self.assertEqual(payload["items"][0]["draft"]["questions"][0]["correctAnswers"], ["Park the car."])
        self.assertFalse((self.root / "data" / "jobs" / str(job_id)).exists())


if __name__ == "__main__":
    unittest.main()
