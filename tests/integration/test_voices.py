from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    VoiceTitleTakenError,
)
from backend.app.db.models.user import User, UserStatus
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.authorization import AuthorizationService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VoiceIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{root / 'voices.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.storage = VoiceStorage(root / "data")
        self.service = VoiceService(self.storage)

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

    def test_first_voice_uses_id_directory_and_automatic_author_tag(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            voice = self.service.create_voice(
                session,
                author=author,
                title="  Ｅnglish Voice  ",
            )
            session.commit()

            self.assertEqual(voice.id, 1)
            self.assertEqual(voice.title, "English Voice")
            self.assertEqual(voice.normalized_title, "english voice")
            self.assertEqual(self.storage.directory(voice.id).name, "1")
            self.assertTrue(self.storage.directory(voice.id).is_dir())
            self.assertEqual(len(voice.tags), 1)
            self.assertEqual(voice.tags[0].type, VoiceTagType.AUTHOR)
            self.assertEqual(voice.tags[0].value, "TeacherOne")

    def test_voice_titles_are_globally_unique_after_normalization(self) -> None:
        with self.session_factory() as session:
            first_author = self.create_author(session, "TeacherOne")
            second_author = self.create_author(session, "TeacherTwo")
            first = self.service.create_voice(
                session,
                author=first_author,
                title="Shared Voice",
            )
            other = self.service.create_voice(
                session,
                author=second_author,
                title="Other Voice",
            )

            with self.assertRaises(VoiceTitleTakenError):
                self.service.create_voice(
                    session,
                    author=second_author,
                    title="  ＳＨＡＲＥＤ ＶＯＩＣＥ  ",
                )
            with self.assertRaises(VoiceTitleTakenError):
                self.service.update_title(session, other, "shared voice")

            self.service.update_title(session, first, "Ｓhared Ｖoice")
            self.assertEqual(first.title, "Shared Voice")
            self.assertEqual(other.title, "Other Voice")

            session.commit()
            session.add(
                Voice(
                    author_id=second_author.id,
                    title="Database duplicate",
                    normalized_title="shared voice",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()

    def test_path_and_atomic_replacement_ignore_resource_text(self) -> None:
        model_temporary = self.storage.create_temporary_file(1, VoiceAsset.MODEL)
        model_temporary.write_bytes(b"model")
        model_path = self.storage.atomic_replace(
            1,
            VoiceAsset.MODEL,
            model_temporary,
        )

        self.assertEqual(model_path, self.storage.root / "1" / "voice.pt")
        self.assertEqual(model_path.read_bytes(), b"model")
        self.assertTrue(self.storage.exists(1))
        for invalid_id in (0, -1, True, "../2"):
            with self.subTest(voice_id=invalid_id), self.assertRaises(ValueError):
                self.storage.directory(invalid_id)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.storage.atomic_replace(
                1,
                VoiceAsset.MODEL,
                Path(self.temporary_dir.name) / "request-name.pt",
            )

        self.storage.delete(1)
        self.assertFalse(self.storage.directory(1).exists())

    def test_status_visibility_and_synthesis_require_ready_model(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            voice = self.service.create_voice(
                session,
                author=author,
                title="State test",
            )
            authorization = AuthorizationService()
            principal = Principal(author)

            with self.assertRaises(ConflictError):
                self.service.set_visibility(session, voice, VoiceVisibility.PUBLIC)
            self.assertFalse(
                authorization.can_use_for_synthesis(
                    principal,
                    self.service.descriptor(voice),
                )
            )
            with self.assertRaises(ConflictError):
                self.service.transition_status(session, voice, VoiceStatus.READY)

            self.service.transition_status(session, voice, VoiceStatus.PROCESSING)
            temporary = self.storage.create_temporary_file(voice.id, VoiceAsset.MODEL)
            temporary.write_bytes(b"model")
            self.storage.atomic_replace(voice.id, VoiceAsset.MODEL, temporary)
            self.service.transition_status(session, voice, VoiceStatus.READY)
            self.service.set_visibility(session, voice, VoiceVisibility.PUBLIC)

            self.assertTrue(
                authorization.can_use_for_synthesis(
                    principal,
                    self.service.descriptor(voice),
                )
            )
            with self.assertRaises(ConflictError):
                self.service.transition_status(session, voice, VoiceStatus.PROCESSING)

    def test_failed_transition_records_summary_and_is_terminal(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            voice = self.service.create_voice(
                session,
                author=author,
                title="Failure test",
            )
            self.service.transition_status(session, voice, VoiceStatus.PROCESSING)
            self.service.transition_status(
                session,
                voice,
                VoiceStatus.FAILED,
                error_summary="  model failed  ",
            )

            self.assertEqual(voice.error_summary, "model failed")
            self.assertEqual(voice.visibility, VoiceVisibility.PRIVATE)
            with self.assertRaises(ConflictError):
                self.service.transition_status(session, voice, VoiceStatus.PROCESSING)

    def test_example_source_and_title_validation(self) -> None:
        with self.session_factory() as session:
            author = self.create_author(session)
            for title in ("", " " * 3, "x" * 201):
                with self.subTest(title=title), self.assertRaises(
                    DomainValidationError
                ):
                    self.service.create_voice(session, author=author, title=title)


if __name__ == "__main__":
    unittest.main()
