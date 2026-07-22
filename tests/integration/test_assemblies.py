from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
import wave
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
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.user import UserRole
from backend.app.factory import create_app
from backend.app.integrations.identity import DEBUG_ISSUER_HEADER, DEBUG_SUBJECT_HEADER
from backend.app.repositories.users import UserRepository
from backend.app.services.assemblies import ASSEMBLY_JOB_TYPE, AssemblyService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audios import AudioQuestionInput, AudioService
from backend.app.services.job_storage import ASSEMBLY_PREVIEW_JOB_TYPE, JobStorage
from backend.app.workers.assemblies import (
    AssemblyJobHandler,
    AssemblyPreviewJobHandler,
)
from backend.app.workers.jobs import JobWorker


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AssemblyIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'assemblies.sqlite3'}"
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
        self.profile("user", "AssemblyTeacher")
        self.profile("admin", "TemplateAdmin")
        with self.app.state.session_factory() as session:
            admin = UserRepository().get_by_user_id(session, "TemplateAdmin")
            assert admin is not None
            admin.role = UserRole.ADMIN
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

    def profile(self, subject: str, user_id: str) -> None:
        response = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.headers(subject),
            json={"userId": user_id, "username": user_id},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def ready_audio(self, title: str, question_count: int, text: str) -> int:
        with self.app.state.session_factory() as session:
            user = UserRepository().get_by_user_id(session, "AssemblyTeacher")
            assert user is not None
            service = AudioService(self.storage)
            audio = service.create_audio(
                session,
                author=user,
                title=title,
                source_type=AudioSourceType.CORPUS,
                text=text,
                questions=[
                    AudioQuestionInput(
                        f"Question {position + 1}?",
                        ("Correct",),
                        ("Incorrect",),
                    )
                    for position in range(question_count)
                ],
            )
            service.transition_status(session, audio, AudioStatus.PROCESSING)
            self.write_wav(self.storage.path(audio.id), 100)
            service.record_file_metadata(session, audio)
            service.transition_status(session, audio, AudioStatus.READY)
            service.set_visibility(session, audio, AudioVisibility.PUBLIC)
            session.commit()
            return audio.id

    @staticmethod
    def write_wav(path: Path, duration_milliseconds: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = 8000 * duration_milliseconds // 1000
        frames = struct.pack("<h", 1000) * frame_count
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(frames)

    def test_dynamic_smart_segment_and_metadata_assembly(self) -> None:
        previous = self.ready_audio("Nine questions", 9, "Excluded text")
        placeholder = self.ready_audio("Two questions", 2, "Included text")
        prefix = self.ready_audio("pre_10-11", 0, "Question numbers")
        with self.app.state.session_factory() as session:
            prefix_audio = session.get(Audio, prefix)
            assert prefix_audio is not None
            prefix_audio.tags.append(
                AudioTagService().create_user_tag(
                    session,
                    tag_type=AudioTagType.TOPIC,
                    english_value="question_instructions",
                )
            )
            session.commit()

        response = self.send(
            "POST",
            "/api/assemblies",
            headers=self.headers("user"),
            json={
                "title": "Dynamic full paper",
                "segments": [
                    {
                        "type": "audio",
                        "audioId": previous,
                        "repeatCount": 2,
                        "repeatIntervalMilliseconds": 50,
                        "includeText": False,
                    },
                    {
                        "type": "comment",
                        "commentText": "Section directions",
                        "includeText": True,
                    },
                    {
                        "type": "comment",
                        "commentText": "Internal note",
                        "includeText": False,
                    },
                    {
                        "type": "smart",
                        "includeText": True,
                        "includeTopic": True,
                    },
                    {"type": "silence", "silenceMilliseconds": 25},
                    {
                        "type": "smart",
                        "smartMode": "question_count_silence",
                        "smartSilenceNext": True,
                        "silenceMilliseconds": 25,
                    },
                    {"type": "placeholder", "audioId": placeholder},
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        audio_id = response.json()["audioId"]
        job_id = response.json()["jobId"]
        self.assertTrue(
            JobStorage(self.settings.data_dir).assembly_input_path(job_id).is_file()
        )
        worker = JobWorker(
            self.app.state.session_factory,
            {ASSEMBLY_JOB_TYPE: AssemblyJobHandler(AssemblyService(self.storage))},
            poll_interval_seconds=0.01,
        )
        self.assertTrue(worker.run_once())

        detail = self.send(
            "GET",
            f"/api/audios/{audio_id}",
            headers=self.headers("user"),
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        body = detail.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["sourceType"], "assembly")
        self.assertEqual(
            body["text"],
            "Section directions\n\nQuestion numbers\n\nIncluded text",
        )
        self.assertEqual(len(body["questions"]), 11)
        self.assertIn(
            ("category", "full_paper"),
            {(tag["type"], tag["englishValue"]) for tag in body["tags"]},
        )
        self.assertIn(
            ("topic", "question_instructions"),
            {(tag["type"], tag["englishValue"]) for tag in body["tags"]},
        )
        self.assertIn(
            ("other", "11_question"),
            {(tag["type"], tag["englishValue"]) for tag in body["tags"]},
        )
        with wave.open(str(self.storage.path(audio_id)), "rb") as output:
            self.assertAlmostEqual(output.getnframes() / 8000, 0.525, delta=0.02)
        self.assertTrue(self.storage.path(prefix).is_file())
        self.assertFalse(self.storage.job_directory(job_id).exists())

        with self.app.state.session_factory() as session:
            retried = AssemblyService(self.storage).process(
                session,
                audio_id=audio_id,
                job_id=job_id,
                owner_id=1,
                visibility=AudioVisibility.PRIVATE,
                checkpoint=lambda progress: None,
            )
            self.assertEqual(retried.id, audio_id)

        draft = self.send(
            "GET",
            f"/api/audios/{audio_id}/creation-draft",
            headers=self.headers("user"),
        )
        self.assertEqual(draft.status_code, 409)

    def test_only_admin_can_create_templates(self) -> None:
        payload = {
            "title": "Structured exam",
            "segments": [
                {"type": "smart"},
                {"type": "silence", "silenceMilliseconds": 25},
                {"type": "placeholder", "suggestedQuery": "topic:news"},
                {
                    "type": "smart",
                    "smartMode": "question_count_silence",
                    "smartSilencePrevious": True,
                    "silenceMilliseconds": 5000,
                },
                {
                    "type": "comment",
                    "commentText": "Read the directions",
                    "includeText": False,
                },
            ],
        }
        forbidden = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("user"),
            json=payload,
        )
        created = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("admin"),
            json=payload,
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(
            created.json()["segments"][2]["suggestedQuery"],
            "topic:news",
        )
        self.assertEqual(
            created.json()["segments"][0]["smartMode"],
            "question_number",
        )
        self.assertEqual(
            created.json()["segments"][3]["smartMode"],
            "question_count_silence",
        )
        self.assertTrue(created.json()["segments"][3]["smartSilencePrevious"])
        self.assertEqual(created.json()["segments"][3]["silenceMilliseconds"], 5000)
        self.assertEqual(created.json()["segments"][4]["type"], "comment")
        self.assertEqual(
            created.json()["segments"][4]["commentText"],
            "Read the directions",
        )
        self.assertFalse(created.json()["segments"][4]["includeText"])

        invalid_comment = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("admin"),
            json={
                "title": "Invalid empty comment",
                "segments": [{"type": "comment", "commentText": "  "}],
            },
        )
        self.assertEqual(invalid_comment.status_code, 422, invalid_comment.text)

    def test_assembly_endpoints_have_no_fixed_segment_limit(self) -> None:
        silence_segments = [
            {"type": "silence", "silenceMilliseconds": 1000}
            for _ in range(200)
        ]
        template = self.send(
            "POST",
            "/api/assembly-templates",
            headers=self.headers("admin"),
            json={
                "title": "Complete exam template",
                "segments": [*silence_segments, {"type": "placeholder"}],
            },
        )

        self.assertEqual(template.status_code, 201, template.text)
        self.assertEqual(len(template.json()["segments"]), 201)

        audio_id = self.ready_audio("Unlimited assembly", 0, "Audio")
        assembly = self.send(
            "POST",
            "/api/assemblies",
            headers=self.headers("user"),
            json={
                "title": "Long complete exam",
                "segments": [
                    *silence_segments,
                    {"type": "audio", "audioId": audio_id},
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(assembly.status_code, 202, assembly.text)

        preview = self.send(
            "POST",
            "/api/assembly-previews",
            headers=self.headers("user"),
            json={
                "segments": [
                    *silence_segments,
                    {"type": "audio", "audioId": audio_id},
                ],
                "startIndex": 200,
                "endIndex": 200,
            },
        )
        self.assertEqual(preview.status_code, 202, preview.text)

    def test_question_count_silence_requires_exactly_one_placeholder(self) -> None:
        previous = self.ready_audio("Previous questions", 2, "Previous")
        following = self.ready_audio("Following question", 1, "Following")
        invalid = self.send(
            "POST",
            "/api/assemblies",
            headers=self.headers("user"),
            json={
                "title": "Invalid smart silence",
                "segments": [
                    {
                        "type": "smart",
                        "smartMode": "question_count_silence",
                        "smartSilencePrevious": True,
                        "silenceMilliseconds": 25,
                    },
                    {"type": "placeholder", "audioId": following},
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(invalid.status_code, 422, invalid.text)

        response = self.send(
            "POST",
            "/api/assemblies",
            headers=self.headers("user"),
            json={
                "title": "Invalid bidirectional smart silence",
                "segments": [
                    {"type": "placeholder", "audioId": previous},
                    {
                        "type": "smart",
                        "smartMode": "question_count_silence",
                        "smartSilencePrevious": True,
                        "smartSilenceNext": True,
                        "silenceMilliseconds": 25,
                    },
                    {"type": "placeholder", "audioId": following},
                ],
                "tagIds": [],
                "visibility": "private",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_preview_renders_selected_suffix_and_protects_temporary_media(self) -> None:
        previous = self.ready_audio("Three questions", 3, "Previous")
        prefix = self.ready_audio("pre_4", 0, "Question number")
        placeholder = self.ready_audio("One question", 1, "Selected")
        response = self.send(
            "POST",
            "/api/assembly-previews",
            headers=self.headers("user"),
            json={
                "segments": [
                    {"type": "audio", "audioId": previous},
                    {"type": "silence", "silenceMilliseconds": 25},
                    {"type": "smart", "includeText": False},
                    {
                        "type": "placeholder",
                        "audioId": placeholder,
                        "repeatCount": 2,
                        "repeatIntervalMilliseconds": 50,
                    },
                ],
                "startIndex": 1,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["jobId"]
        pending_media = self.send(
            "GET",
            f"/media/assembly-preview/{job_id}",
            headers=self.headers("user"),
        )
        self.assertEqual(pending_media.status_code, 409, pending_media.text)

        worker = JobWorker(
            self.app.state.session_factory,
            {
                ASSEMBLY_PREVIEW_JOB_TYPE: AssemblyPreviewJobHandler(
                    AssemblyService(self.storage)
                )
            },
            poll_interval_seconds=0.01,
            job_storage=JobStorage(self.settings.data_dir),
        )
        self.assertTrue(worker.run_once())
        foreign_media = self.send(
            "GET",
            f"/media/assembly-preview/{job_id}",
            headers=self.headers("admin"),
        )
        self.assertEqual(foreign_media.status_code, 404, foreign_media.text)
        media = self.send(
            "GET",
            f"/media/assembly-preview/{job_id}",
            headers=self.headers("user"),
        )
        self.assertEqual(media.status_code, 200, media.text)
        self.assertEqual(media.headers["cache-control"], "private, no-store")

        preview_path = JobStorage(self.settings.data_dir).assembly_preview_path(job_id)
        with wave.open(str(preview_path), "rb") as output:
            self.assertAlmostEqual(output.getnframes() / 8000, 0.375, delta=0.02)
        self.assertTrue(self.storage.path(prefix).is_file())

        deleted = self.send(
            "DELETE",
            f"/api/assembly-previews/{job_id}",
            headers=self.headers("user"),
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertFalse(JobStorage(self.settings.data_dir).directory(job_id).exists())


if __name__ == "__main__":
    unittest.main()
