from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioUtterance,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTagType
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import Voice
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.audios import AudioService, AudioUtteranceInput
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{root / 'audios.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        data_dir = root / "data"
        self.storage = AudioStorage(data_dir)
        self.service = AudioService(self.storage)
        self.voice_service = VoiceService(VoiceStorage(data_dir))

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    def create_author(session: Session, user_id: str = "TeacherOne") -> User:
        author = User(
            issuer="https://issuer.example",
            subject=user_id,
            status=UserStatus.ACTIVE,
            user_id=user_id,
            normalized_user_id=user_id.lower(),
            username="Teacher",
        )
        session.add(author)
        session.flush()
        return author

    def create_voice(self, session: Session, author: User, title: str) -> Voice:
        return self.voice_service.create_voice(
            session,
            author=author,
            title=title,
        )

    @staticmethod
    def write_wav(path: Path) -> None:
        with wave.open(str(path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 800)

    def test_first_audio_path_author_and_requested_tags(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            topic = AudioTagService().create_tag(
                session,
                tag_type=AudioTagType.TOPIC,
                english_value="Climate Change",
            )
            audio = self.service.create_audio(
                session,
                author=author,
                title="  Ｌistening One  ",
                source_type=AudioSourceType.CORPUS,
                text="Generated passage",
                tags=[topic],
            )
            session.commit()

            self.assertEqual(audio.id, 1)
            self.assertEqual(audio.title, "Listening One")
            self.assertEqual(audio.normalized_title, "listening one")
            self.assertEqual(self.storage.path(audio.id).name, "audio.wav")
            self.assertEqual(self.storage.directory(audio.id).name, "1")
            self.assertTrue(self.storage.directory(audio.id).is_dir())
            self.assertEqual(
                {(tag.type, tag.value) for tag in audio.tags},
                {
                    (AudioTagType.TOPIC, "Climate_Change"),
                    (AudioTagType.AUTHOR, "TeacherOne"),
                },
            )

    def test_multi_turn_order_full_text_foreign_key_and_cascade(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            first_voice = self.create_voice(session, author, "First voice")
            second_voice = self.create_voice(session, author, "Second voice")
            audio = self.service.create_audio(
                session,
                author=author,
                title="Dialogue",
                source_type=AudioSourceType.MULTI_TURN,
                utterances=[
                    AudioUtteranceInput(
                        voice_id=second_voice.id,
                        speaker_display_name="Bob",
                        text="Second line.",
                    ),
                    AudioUtteranceInput(
                        voice_id=first_voice.id,
                        speaker_display_name="Alice",
                        text="First line.",
                    ),
                ],
            )
            session.commit()
            audio_id = audio.id
            first_voice_id = first_voice.id

        with self.session_factory() as session:
            audio = session.get(Audio, audio_id)
            self.assertIsNotNone(audio)
            assert audio is not None
            self.assertEqual(
                [utterance.position for utterance in audio.utterances],
                [0, 1],
            )
            self.assertEqual(
                [utterance.speaker_display_name for utterance in audio.utterances],
                ["Bob", "Alice"],
            )
            self.assertEqual(audio.text, "Bob: Second line.\nAlice: First line.")

            referenced_voice = session.get(Voice, first_voice_id)
            session.delete(referenced_voice)
            session.commit()
            session.expire_all()
            audio = session.get(Audio, audio_id)
            assert audio is not None
            self.assertEqual(
                [utterance.voice_id for utterance in audio.utterances],
                [second_voice.id, None],
            )
            self.assertEqual(
                [utterance.speaker_display_name for utterance in audio.utterances],
                ["Bob", "Alice"],
            )

        with self.session_factory() as session:
            audio = session.get(Audio, audio_id)
            session.delete(audio)
            session.commit()
            utterance_count = session.scalar(
                select(func.count()).select_from(AudioUtterance)
            )
            self.assertEqual(utterance_count, 0)

    def test_file_metadata_status_and_playback(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            audio = self.service.create_audio(
                session,
                author=author,
                title="Playback",
                source_type=AudioSourceType.SINGLE_SPEAKER,
                text="Playback text",
            )

            self.assertEqual(audio.status, AudioStatus.PENDING)
            with self.assertRaises(ConflictError):
                self.service.playback_path(audio)
            with self.assertRaises(ConflictError):
                self.service.set_visibility(session, audio, AudioVisibility.PUBLIC)

            self.service.transition_status(session, audio, AudioStatus.PROCESSING)
            temporary_path = self.storage.temporary_audio_path(1)
            self.write_wav(temporary_path)
            final_path = self.storage.atomic_replace(audio.id, 1)
            self.service.record_file_metadata(session, audio)
            self.service.transition_status(session, audio, AudioStatus.READY)
            self.service.set_visibility(session, audio, AudioVisibility.PUBLIC)

            self.assertEqual(self.service.playback_path(audio), final_path)
            self.assertEqual(audio.audio_format, "wav")
            self.assertAlmostEqual(audio.duration_seconds or 0, 0.1)
            self.assertEqual(audio.sample_rate, 8000)
            self.assertEqual(audio.channels, 1)
            self.assertEqual(audio.sample_width_bytes, 2)
            self.assertEqual(audio.file_size_bytes, final_path.stat().st_size)
            with self.assertRaises(ConflictError):
                self.service.transition_status(session, audio, AudioStatus.PROCESSING)

            self.storage.cleanup_job(1)
            self.assertFalse(self.storage.job_directory(1).exists())

    def test_invalid_temporary_audio_and_source_rules_are_rejected(self) -> None:
        with self.assertRaises(ConflictError):
            self.storage.atomic_replace(1, 1)
        for invalid_id in (0, -1, True, "../2"):
            with self.subTest(identifier=invalid_id), self.assertRaises(ValueError):
                self.storage.path(invalid_id)  # type: ignore[arg-type]

        with self.session_factory() as session:
            author = self.create_author(session)
            with self.assertRaises(DomainValidationError):
                self.service.create_audio(
                    session,
                    author=author,
                    title="Invalid dialogue",
                    source_type=AudioSourceType.MULTI_TURN,
                    text="Only one block",
                )


if __name__ == "__main__":
    unittest.main()
