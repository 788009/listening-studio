from __future__ import annotations

import io
import tempfile
import unittest
import wave
from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    JobFailedError,
)
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voice_tags import VoiceTagService
from backend.app.services.voice_uploads import (
    ReferenceAudioValidator,
    VoiceUploadService,
)
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeAudioTranscoder:
    def __init__(self, output: bytes) -> None:
        self.output = output
        self.calls: list[tuple[bytes, str, float]] = []

    def convert_to_wav(
        self,
        content: bytes,
        *,
        extension: str,
        max_duration_seconds: float,
    ) -> bytes:
        self.calls.append((content, extension, max_duration_seconds))
        return self.output


class VoiceUploadIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'voice-uploads.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.storage = VoiceStorage(self.root / "data")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def create_author(session: Session) -> User:
        author = User(
            issuer="https://issuer.example",
            subject="teacher",
            status=UserStatus.ACTIVE,
            user_id="TeacherOne",
            normalized_user_id="teacherone",
            username="Teacher",
        )
        session.add(author)
        session.flush()
        return author

    @staticmethod
    def wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(sample_rate)
            audio_file.writeframes(
                b"\x00\x00" * int(duration_seconds * sample_rate)
            )
        return output.getvalue()

    def service(
        self,
        integration: FakeCosyVoiceIntegration,
        *,
        max_upload_bytes: int = 1024 * 1024,
        audio_transcoder: FakeAudioTranscoder | None = None,
    ) -> VoiceUploadService:
        return VoiceUploadService(
            integration=integration,
            storage=self.storage,
            max_upload_bytes=max_upload_bytes,
            audio_transcoder=audio_transcoder,
        )

    def test_success_uses_fixed_paths_tags_and_delayed_public_visibility(self) -> None:
        observations: list[tuple[VoiceStatus, VoiceVisibility]] = []
        fake = FakeCosyVoiceIntegration()
        original_extract = fake.extract_voice

        def inspect_and_extract(input_path: Path, output_path: Path) -> Path:
            with self.session_factory() as observer:
                voice = observer.get(Voice, 1)
                assert voice is not None
                observations.append((voice.status, voice.visibility))
            return original_extract(input_path, output_path)

        fake.extract_voice = inspect_and_extract  # type: ignore[method-assign]

        with self.session_factory() as session:
            author = self.create_author(session)
            gender = VoiceTagService().create_user_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="Female",
            )
            voice = self.service(fake).create_from_upload(
                session,
                author=author,
                title="Uploaded voice",
                filename="REFERENCE.WAV",
                content=self.wav_bytes(2.0),
                gender_tag_id=gender.id,
                target_visibility=VoiceVisibility.PUBLIC,
                request_id="request-success",
            )

            self.assertEqual(voice.id, 1)
            self.assertEqual(voice.status, VoiceStatus.READY)
            self.assertEqual(voice.visibility, VoiceVisibility.PUBLIC)
            self.assertEqual(
                {tag.type for tag in voice.tags},
                {VoiceTagType.AUTHOR, VoiceTagType.GENDER},
            )

        self.assertEqual(
            observations,
            [(VoiceStatus.PROCESSING, VoiceVisibility.PRIVATE)],
        )
        self.assertEqual(
            self.storage.path(1, VoiceAsset.MODEL),
            self.root / "data" / "voice" / "1" / "voice.pt",
        )
        self.assertTrue(self.storage.exists(1, VoiceAsset.MODEL))
        self.assertTrue(self.storage.exists(1, VoiceAsset.REFERENCE))
        self.assertEqual(
            {path.name for path in self.storage.directory(1).iterdir()},
            {"voice.pt", "reference.wav"},
        )
        with wave.open(
            str(self.storage.path(1, VoiceAsset.REFERENCE)),
            "rb",
        ) as reference:
            self.assertEqual(reference.getframerate(), 8000)
            self.assertEqual(reference.getnframes(), 16000)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0].operation, "extract_voice")
        self.assertEqual(fake.calls[0].input_path.parent.name, "1")
        self.assertEqual(fake.calls[0].output_path.parent.name, "1")

    def test_compressed_reference_is_converted_before_validation(self) -> None:
        fake = FakeCosyVoiceIntegration()
        transcoder = FakeAudioTranscoder(self.wav_bytes(2.0, sample_rate=16000))

        with self.session_factory() as session:
            author = self.create_author(session)
            voice = self.service(fake, audio_transcoder=transcoder).create_from_upload(
                session,
                author=author,
                title="MP3 voice",
                filename="reference.MP3",
                content=b"compressed-audio",
                request_id="request-mp3",
            )

        self.assertEqual(voice.status, VoiceStatus.READY)
        self.assertEqual(
            transcoder.calls,
            [(b"compressed-audio", ".mp3", 30.0)],
        )
        with wave.open(
            str(self.storage.path(voice.id, VoiceAsset.REFERENCE)),
            "rb",
        ) as reference:
            self.assertEqual(reference.getframerate(), 16000)
            self.assertEqual(reference.getnchannels(), 1)

    def test_validator_accepts_each_supported_compressed_extension(self) -> None:
        transcoder = FakeAudioTranscoder(self.wav_bytes(2.0, sample_rate=16000))
        validator = ReferenceAudioValidator(
            max_upload_bytes=1024 * 1024,
            transcoder=transcoder,
        )

        for extension in (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"):
            with self.subTest(extension=extension):
                reference = validator.validate(
                    f"reference{extension}",
                    b"compressed-audio",
                )
                self.assertEqual(reference.sample_rate, 16000)

        self.assertEqual(
            [extension for _, extension, _ in transcoder.calls],
            [".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"],
        )

    def test_invalid_uploads_are_rejected_before_model_or_record_creation(self) -> None:
        fake = FakeCosyVoiceIntegration()
        valid = self.wav_bytes(2.0)
        invalid_uploads = [
            ("reference.txt", valid, 1024 * 1024),
            ("reference.wav", b"", 1024 * 1024),
            ("reference.wav", b"not a wav", 1024 * 1024),
            ("reference.wav", self.wav_bytes(0.5), 1024 * 1024),
            ("reference.wav", self.wav_bytes(31.0), 1024 * 1024),
            ("reference.wav", valid, 100),
        ]

        with self.session_factory() as session:
            author = self.create_author(session)
            session.commit()
            for filename, content, max_bytes in invalid_uploads:
                with self.subTest(filename=filename, size=len(content)):
                    with self.assertRaises(DomainValidationError):
                        upload_service = self.service(
                            fake,
                            max_upload_bytes=max_bytes,
                        )
                        upload_service.create_from_upload(
                            session,
                            author=author,
                            title="Invalid upload",
                            filename=filename,
                            content=content,
                            request_id="request-invalid",
                        )

            voice_count = session.scalar(select(func.count()).select_from(Voice))

        self.assertEqual(voice_count, 0)
        self.assertEqual(fake.calls, [])

    def test_model_failure_persists_failed_state_and_cleans_files(self) -> None:
        fake = FakeCosyVoiceIntegration(failure=RuntimeError("model exploded"))
        records: list[dict[str, object]] = []
        sink_id = logger.add(lambda message: records.append(message.record))
        try:
            with self.session_factory() as session:
                author = self.create_author(session)
                with self.assertRaises(JobFailedError) as error:
                    self.service(fake).create_from_upload(
                        session,
                        author=author,
                        title="Failed voice",
                        filename="reference.wav",
                        content=self.wav_bytes(2.0),
                        target_visibility=VoiceVisibility.PUBLIC,
                        request_id="request-failure",
                    )
                self.assertEqual(error.exception.details, {"voiceId": 1})
        finally:
            logger.remove(sink_id)

        with self.session_factory() as session:
            voice = session.get(Voice, 1)
            assert voice is not None
            self.assertEqual(voice.status, VoiceStatus.FAILED)
            self.assertEqual(voice.visibility, VoiceVisibility.PRIVATE)
            self.assertEqual(
                voice.error_summary,
                "Voice generation failed (RuntimeError)",
            )
            with self.assertRaises(ConflictError):
                VoiceService(self.storage).set_visibility(
                    session,
                    voice,
                    VoiceVisibility.PUBLIC,
                )

        self.assertFalse(self.storage.directory(1).exists())
        failure_records = [
            record
            for record in records
            if "Voice upload failed" in record["message"]
        ]
        self.assertEqual(len(failure_records), 1)
        self.assertIn("voice_id=1", failure_records[0]["message"])
        self.assertEqual(
            failure_records[0]["extra"]["request_id"],
            "request-failure",
        )


if __name__ == "__main__":
    unittest.main()
