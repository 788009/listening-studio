from __future__ import annotations

import asyncio
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchStatus,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.paper import Paper, PaperStatus
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.factory import create_app
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.integrations.identity import ExternalIdentity
from backend.app.integrations.llm import (
    GeneratedDialogueTurn,
    GeneratedListeningContent,
    ListeningGenerationRequest,
    ListeningGenerationResult,
    ValidatingListeningContentGenerator,
)
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import CORPUS_GENERATION_JOB_TYPE
from backend.app.services.job_storage import JobStorage
from backend.app.services.paper_rendering import (
    PAPER_RENDER_JOB_TYPE,
    PaperRenderService,
)
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voice_uploads import (
    VOICE_UPLOAD_JOB_TYPE,
    VoiceUploadService,
)
from backend.app.workers.audio_synthesis import AudioSynthesisJobHandler
from backend.app.workers.corpus_generation import CorpusGenerationJobHandler
from backend.app.workers.jobs import JobWorker
from backend.app.workers.paper_rendering import PaperRenderJobHandler
from backend.app.workers.voice_upload import VoiceUploadJobHandler


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OIDC_SUBJECT_HEADER = "X-Test-OIDC-Subject"


class FakeOidcIdentityProvider:
    def __init__(self) -> None:
        self.authenticated_subjects: list[str] = []

    async def authenticate(self, request: Request) -> ExternalIdentity | None:
        subject = request.headers.get(OIDC_SUBJECT_HEADER)
        if not subject:
            return None
        self.authenticated_subjects.append(subject)
        return ExternalIdentity(
            issuer="https://fake-oidc.example",
            subject=subject,
        )


class FakeListeningContentGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[ListeningGenerationRequest, str]] = []

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> ListeningGenerationResult:
        self.calls.append((request, call_id))
        question_types = sorted(request.question_types, key=lambda item: item.value)
        return ListeningGenerationResult(
            items=[
                GeneratedListeningContent(
                    title="Generated climate interview",
                    turns=[
                        GeneratedDialogueTurn(
                            speaker="Host",
                            text="What can schools do about climate change?",
                        ),
                        GeneratedDialogueTurn(
                            speaker="Guest",
                            text="They can teach practical ways to reduce waste.",
                        ),
                    ],
                    question_types=question_types,
                    suggested_topics=["climate_change"],
                    suggested_categories=["interview"],
                )
            ]
        )


class FullWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'workflow.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            debug_auth_enabled=False,
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=self.root / "missing-model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
            dialogue_silence_milliseconds=25,
        )
        self.oidc = FakeOidcIdentityProvider()
        self.app = create_app(self.settings, identity_provider=self.oidc)
        self.voice_storage = VoiceStorage(self.settings.data_dir)
        self.audio_storage = AudioStorage(self.settings.data_dir)
        self.job_storage = JobStorage(self.settings.data_dir)
        self.tts = FakeCosyVoiceIntegration()
        self.llm = FakeListeningContentGenerator()
        self.worker = self._worker()
        self.cosyvoice_import_patcher = patch(
            "backend.app.integrations.cosyvoice.importlib.import_module"
        )
        self.cosyvoice_import = self.cosyvoice_import_patcher.start()
        self.addCleanup(self.cosyvoice_import_patcher.stop)

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()
        self.assertFalse(self.root.exists(), "temporary workflow directory was retained")

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
    def teacher_headers(
        request_id: str,
        *,
        subject: str = "teacher-subject",
    ) -> dict[str, str]:
        return {
            OIDC_SUBJECT_HEADER: subject,
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
            f"{stage}: expected HTTP {expected}, got {response.status_code}: "
            f"{response.text}",
        )

    @staticmethod
    def wav_bytes(duration_seconds: float = 2.0) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * int(duration_seconds * 8000))
        return output.getvalue()

    def _worker(self) -> JobWorker:
        synthesis_service = AudioSynthesisService(
            audio_storage=self.audio_storage,
            voice_storage=self.voice_storage,
            integration=self.tts,
        )
        corpus_service = CorpusGenerationService(
            generator=ValidatingListeningContentGenerator(self.llm),
            corpus_storage=CorpusStorage(self.settings.data_dir),
            synthesis_service=synthesis_service,
            voice_storage=self.voice_storage,
            silence_milliseconds=self.settings.dialogue_silence_milliseconds,
        )
        voice_service = VoiceUploadService(
            storage=self.voice_storage,
            max_upload_bytes=self.settings.max_upload_bytes,
            integration=self.tts,
            job_storage=self.job_storage,
        )
        return JobWorker(
            self.app.state.session_factory,
            {
                VOICE_UPLOAD_JOB_TYPE: VoiceUploadJobHandler(voice_service),
                AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(
                    synthesis_service
                ),
                CORPUS_GENERATION_JOB_TYPE: CorpusGenerationJobHandler(
                    corpus_service
                ),
                PAPER_RENDER_JOB_TYPE: PaperRenderJobHandler(
                    PaperRenderService(self.audio_storage)
                ),
            },
            poll_interval_seconds=0.01,
            job_storage=self.job_storage,
        )

    def run_jobs(self, count: int, stage: str) -> None:
        for position in range(count):
            self.assertTrue(
                self.worker.run_once(),
                f"{stage}: worker found no job at position {position}",
            )
        self.assertFalse(
            self.worker.run_once(),
            f"{stage}: unexpected queued job remained",
        )

    def upload_voice(
        self,
        title: str,
        gender_tag_id: int,
        *,
        visibility: str,
        request_id: str,
    ) -> tuple[int, int]:
        response = self.send(
            "POST",
            "/api/voices",
            headers=self.teacher_headers(request_id),
            data={
                "title": title,
                "genderTagId": str(gender_tag_id),
                "visibility": visibility,
            },
            files={"file": ("reference.wav", self.wav_bytes(), "audio/wav")},
        )
        self.assert_status(response, 202, f"{request_id} voice upload")
        return response.json()["voiceId"], response.json()["jobId"]

    def test_teacher_to_student_full_workflow(self) -> None:
        anonymous = self.send("GET", "/api/users/me")
        self.assert_status(anonymous, 401, "anonymous teacher endpoint")

        first_login = self.send(
            "GET",
            "/api/users/me",
            headers={
                **self.teacher_headers("first-login"),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        self.assert_status(first_login, 200, "fake OIDC first login")
        self.assertEqual(first_login.json()["profileComplete"], False)
        self.assertEqual(first_login.json()["locale"], "zh-CN")
        with self.app.state.session_factory() as session:
            pending_user = session.scalar(select(User))
            self.assertIsNotNone(pending_user, "first login did not create a user")
            assert pending_user is not None
            self.assertEqual(pending_user.status, UserStatus.PENDING_PROFILE)
            self.assertEqual(pending_user.issuer, "https://fake-oidc.example")
            self.assertEqual(pending_user.subject, "teacher-subject")

        profile = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.teacher_headers("complete-profile"),
            json={
                "userId": "TeacherOne",
                "username": "Teacher One",
                "locale": "en",
            },
        )
        self.assert_status(profile, 200, "complete teacher profile")
        self.assertTrue(profile.json()["profileComplete"])

        gender = self.send(
            "POST",
            "/api/voice-tags",
            headers=self.teacher_headers("create-gender-tag"),
            json={
                "type": "gender",
                "value": "female",
                "translations": [{"language": "zh-CN", "value": "女性"}],
            },
        )
        topic = self.send(
            "POST",
            "/api/audio-tags",
            headers=self.teacher_headers("create-topic-tag"),
            json={
                "type": "topic",
                "value": "climate change",
                "translations": [{"language": "zh-CN", "value": "气候变化"}],
            },
        )
        self.assert_status(gender, 201, "create voice tag")
        self.assert_status(topic, 201, "create audio tag")
        gender_tag_id = gender.json()["id"]
        topic_tag_id = topic.json()["id"]

        host_voice_id, host_job_id = self.upload_voice(
            "Host voice",
            gender_tag_id,
            visibility="public",
            request_id="upload-host",
        )
        guest_voice_id, guest_job_id = self.upload_voice(
            "Guest voice",
            gender_tag_id,
            visibility="private",
            request_id="upload-guest",
        )
        self.run_jobs(2, "voice generation")

        with self.app.state.session_factory() as session:
            voices = [
                session.get(Voice, voice_id)
                for voice_id in (host_voice_id, guest_voice_id)
            ]
            self.assertTrue(all(voices), "voice records are missing after generation")
            ready_voices = [voice for voice in voices if voice is not None]
            self.assertTrue(
                all(voice.status is VoiceStatus.READY for voice in ready_voices)
            )
            self.assertEqual(ready_voices[0].visibility, VoiceVisibility.PUBLIC)
            self.assertEqual(ready_voices[1].visibility, VoiceVisibility.PRIVATE)
            for voice in ready_voices:
                self.assertEqual(
                    {(tag.type, tag.value) for tag in voice.tags},
                    {
                        (VoiceTagType.AUTHOR, "TeacherOne"),
                        (VoiceTagType.GENDER, "female"),
                    },
                )
        for voice_id in (host_voice_id, guest_voice_id):
            self.assertTrue(
                self.voice_storage.exists(voice_id, VoiceAsset.MODEL),
                f"voice {voice_id} model file is missing",
            )
            self.assertTrue(
                self.voice_storage.exists(voice_id, VoiceAsset.REFERENCE),
                f"voice {voice_id} reference file is missing",
            )

        single = self.send(
            "POST",
            "/api/audios",
            headers=self.teacher_headers("submit-single"),
            json={
                "title": "Public climate lesson",
                "text": "Students discuss practical climate action.",
                "voiceId": host_voice_id,
                "tagIds": [topic_tag_id],
                "visibility": "private",
            },
        )
        dialogue = self.send(
            "POST",
            "/api/audios/dialogues",
            headers=self.teacher_headers("submit-dialogue"),
            json={
                "title": "Private classroom dialogue",
                "utterances": [
                    {
                        "voiceId": host_voice_id,
                        "speakerDisplayName": "Tutor",
                        "text": "What did you learn today?",
                    },
                    {
                        "voiceId": guest_voice_id,
                        "speakerDisplayName": "Learner",
                        "text": "I learned how to reduce waste.",
                    },
                ],
                "tagIds": [topic_tag_id],
                "visibility": "private",
            },
        )
        self.assert_status(single, 202, "submit single-speaker audio")
        self.assert_status(dialogue, 202, "submit multi-speaker audio")
        single_audio_id = single.json()["audioId"]
        dialogue_audio_id = dialogue.json()["audioId"]
        single_job_id = single.json()["jobId"]
        dialogue_job_id = dialogue.json()["jobId"]
        self.run_jobs(2, "single and dialogue generation")

        publish = self.send(
            "PATCH",
            f"/api/audios/{single_audio_id}",
            headers=self.teacher_headers("publish-single"),
            json={"visibility": "public"},
        )
        self.assert_status(publish, 200, "publish generated audio")

        student_search = self.send(
            "GET",
            "/api/audios",
            params={"q": "topic:climate_change"},
        )
        self.assert_status(student_search, 200, "student public audio search")
        self.assertEqual(
            [item["id"] for item in student_search.json()["items"]],
            [single_audio_id],
        )
        private_detail = self.send("GET", f"/api/audios/{dialogue_audio_id}")
        self.assert_status(private_detail, 404, "student private audio access")
        playback = self.send(
            "GET",
            f"/media/audio/{single_audio_id}",
            headers={"Range": "bytes=0-31"},
        )
        self.assert_status(playback, 206, "student public audio playback")
        self.assertEqual(playback.headers["content-type"], "audio/wav")
        self.assertEqual(len(playback.content), 32)
        anonymous_create = self.send(
            "POST",
            "/api/audios",
            json={
                "title": "Unauthorized",
                "text": "Unauthorized",
                "voiceId": host_voice_id,
            },
        )
        self.assert_status(anonymous_create, 401, "student generation permission")

        batch = self.send(
            "POST",
            "/api/generation-batches",
            headers=self.teacher_headers("submit-batch"),
            files=[
                ("questionTypes", (None, "multiple_choice")),
                ("count", (None, "1")),
                ("corpus", (None, "Schools can reduce waste and save energy.")),
                ("tagIds", (None, str(topic_tag_id))),
                (
                    "speakerVoiceMap",
                    (
                        None,
                        json.dumps(
                            {"Host": host_voice_id, "Guest": guest_voice_id}
                        ),
                    ),
                ),
            ],
        )
        self.assert_status(batch, 202, "submit corpus generation batch")
        batch_id = batch.json()["batchId"]
        batch_job_id = batch.json()["jobId"]
        self.run_jobs(1, "corpus batch generation")
        batch_detail = self.send(
            "GET",
            f"/api/generation-batches/{batch_id}",
            headers=self.teacher_headers("read-batch"),
        )
        self.assert_status(batch_detail, 200, "read completed corpus batch")
        self.assertEqual(batch_detail.json()["status"], "completed")
        batch_audio_id = batch_detail.json()["items"][0]["audioId"]

        preset = self.send(
            "POST",
            "/api/paper-presets",
            headers=self.teacher_headers("create-preset"),
            json={
                "name": "Workflow preset",
                "introSilenceMilliseconds": 10,
                "interItemSilenceMilliseconds": 20,
                "repeatCount": 1,
                "outroSilenceMilliseconds": 10,
            },
        )
        self.assert_status(preset, 201, "create paper preset")
        paper = self.send(
            "POST",
            "/api/papers",
            headers=self.teacher_headers("create-paper"),
            json={
                "title": "Climate listening paper",
                "presetId": preset.json()["id"],
                "audioIds": [single_audio_id, dialogue_audio_id, batch_audio_id],
            },
        )
        self.assert_status(paper, 201, "assemble listening paper")
        paper_id = paper.json()["id"]
        render = self.send(
            "POST",
            f"/api/papers/{paper_id}/render",
            headers=self.teacher_headers("render-paper"),
        )
        self.assert_status(render, 202, "submit paper rendering")
        paper_audio_id = render.json()["audioId"]
        paper_job_id = render.json()["jobId"]
        self.run_jobs(1, "paper rendering")

        delete_audio = self.send(
            "DELETE",
            f"/api/audios/{single_audio_id}",
            headers=self.teacher_headers("delete-referenced-audio"),
        )
        self.assert_status(delete_audio, 409, "delete paper source conflict")
        self.assertGreater(
            delete_audio.json()["error"]["details"]["paperItemCount"],
            0,
        )
        delete_voice = self.send(
            "DELETE",
            f"/api/voices/{host_voice_id}",
            headers=self.teacher_headers("delete-used-voice"),
        )
        self.assert_status(delete_voice, 409, "delete used voice conflict")
        self.assertGreater(
            delete_voice.json()["error"]["details"]["audioUtteranceCount"],
            0,
        )

        other_profile = self.send(
            "POST",
            "/api/users/me/profile",
            headers=self.teacher_headers(
                "complete-other-profile",
                subject="other-teacher",
            ),
            json={"userId": "TeacherTwo", "username": "Teacher Two"},
        )
        self.assert_status(other_profile, 200, "complete second teacher profile")
        forbidden_edit = self.send(
            "PATCH",
            f"/api/audios/{single_audio_id}",
            headers=self.teacher_headers(
                "other-teacher-edit",
                subject="other-teacher",
            ),
            json={"title": "Other teacher edit"},
        )
        self.assert_status(forbidden_edit, 403, "cross-owner edit permission")

        job_ids = [
            host_job_id,
            guest_job_id,
            single_job_id,
            dialogue_job_id,
            batch_job_id,
            paper_job_id,
        ]
        with self.app.state.session_factory() as session:
            jobs = list(session.scalars(select(Job).order_by(Job.id)))
            self.assertEqual([job.id for job in jobs], job_ids)
            self.assertTrue(
                all(job.status is JobStatus.SUCCEEDED for job in jobs),
                "not all workflow jobs succeeded",
            )
            teacher = session.scalar(
                select(User).where(User.subject == "teacher-subject")
            )
            self.assertIsNotNone(teacher)
            assert teacher is not None
            single_record = session.get(Audio, single_audio_id)
            dialogue_record = session.get(Audio, dialogue_audio_id)
            batch_record = session.get(GenerationBatch, batch_id)
            batch_audio = session.get(Audio, batch_audio_id)
            paper_record = session.get(Paper, paper_id)
            paper_audio = session.get(Audio, paper_audio_id)
            assert single_record and dialogue_record and batch_record
            assert batch_audio and paper_record and paper_audio
            self.assertEqual(single_record.author_id, teacher.id)
            self.assertEqual(single_record.source_type, AudioSourceType.SINGLE_SPEAKER)
            self.assertEqual(single_record.status, AudioStatus.READY)
            self.assertEqual(single_record.visibility, AudioVisibility.PUBLIC)
            self.assertEqual(
                {(tag.type, tag.value) for tag in single_record.tags},
                {
                    (AudioTagType.AUTHOR, "TeacherOne"),
                    (AudioTagType.TOPIC, "climate_change"),
                },
            )
            self.assertEqual(dialogue_record.source_type, AudioSourceType.MULTI_TURN)
            self.assertEqual(
                [item.speaker_display_name for item in dialogue_record.utterances],
                ["Tutor", "Learner"],
            )
            self.assertEqual(
                [item.position for item in dialogue_record.utterances],
                [0, 1],
            )
            self.assertEqual(
                {(tag.type, tag.value) for tag in dialogue_record.tags},
                {
                    (AudioTagType.AUTHOR, "TeacherOne"),
                    (AudioTagType.SPEAKER, "Tutor"),
                    (AudioTagType.SPEAKER, "Learner"),
                    (AudioTagType.TOPIC, "climate_change"),
                },
            )
            self.assertEqual(batch_record.status, GenerationBatchStatus.COMPLETED)
            self.assertEqual(batch_record.items[0].audio_id, batch_audio_id)
            self.assertEqual(batch_audio.source_type, AudioSourceType.CORPUS)
            self.assertEqual(batch_audio.status, AudioStatus.READY)
            self.assertTrue(
                {
                    (AudioTagType.TOPIC, "climate_change"),
                    (AudioTagType.CATEGORY, "interview"),
                }.issubset({(tag.type, tag.value) for tag in batch_audio.tags})
            )
            self.assertEqual(paper_record.status, PaperStatus.READY)
            self.assertEqual(
                [item.audio_id for item in paper_record.items],
                [single_audio_id, dialogue_audio_id, batch_audio_id],
            )
            self.assertEqual(paper_record.result_audio_id, paper_audio_id)
            self.assertEqual(paper_audio.status, AudioStatus.READY)
            self.assertEqual(paper_audio.source_type, AudioSourceType.ASSEMBLY)

        for audio_id in (
            single_audio_id,
            dialogue_audio_id,
            batch_audio_id,
            paper_audio_id,
        ):
            self.assertTrue(
                self.audio_storage.exists(audio_id),
                f"audio {audio_id} file is missing",
            )
        if self.job_storage.root.exists():
            self.assertEqual(
                list(self.job_storage.root.iterdir()),
                [],
                "completed jobs retained temporary files",
            )

        self.assertEqual(len(self.llm.calls), 1)
        self.assertEqual(self.llm.calls[0][1], f"job-{batch_job_id}")
        self.assertEqual(
            [call.operation for call in self.tts.calls].count("extract_voice"),
            2,
        )
        self.assertEqual(
            [call.operation for call in self.tts.calls].count("synthesize"),
            5,
        )
        self.cosyvoice_import.assert_not_called()

        log_text = (self.settings.log_dir / "backend.log").read_text(encoding="utf-8")
        log_lines = log_text.splitlines()
        for request_id, message in (
            ("upload-host", "Voice upload submitted"),
            ("submit-single", "Audio synthesis submitted"),
            ("submit-dialogue", "Dialogue synthesis submitted"),
            ("submit-batch", "Corpus generation batch submitted"),
            ("render-paper", "Paper rendering submitted"),
        ):
            self.assertTrue(
                any(
                    f"request_id={request_id}" in line and message in line
                    for line in log_lines
                ),
                f"{message} structured request log is missing",
            )
        for job_id in job_ids:
            self.assertIn(
                f"request_id=job-{job_id} job_id={job_id}",
                log_text,
                f"job {job_id} structured log context is missing",
            )
            self.assertIn(
                f"Job completed job_id={job_id}",
                log_text,
                f"job {job_id} completion log is missing",
            )
        self.assertIn("paperItemCount", delete_audio.text)
        self.assertIn("audioUtteranceCount", delete_voice.text)
        self.assertIn("teacher-subject", self.oidc.authenticated_subjects)


if __name__ == "__main__":
    unittest.main()
