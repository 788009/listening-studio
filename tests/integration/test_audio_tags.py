from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.audio_tags import AudioTagService
from backend.app.services.tag_values import TagTranslationInput
from backend.app.services.voice_tags import VoiceTagService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AudioTagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_dir.name) / "audio-tags.sqlite3"
        database_url = f"sqlite:///{database_path}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.service = AudioTagService()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_dir.cleanup()

    def test_audio_and_voice_tag_ids_are_independent(self) -> None:
        with self.session_factory() as session:
            voice_tag = VoiceTagService().create_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="male",
            )
            audio_tag = self.service.create_tag(
                session,
                tag_type=AudioTagType.SPEAKER,
                english_value="male",
            )
            session.commit()

            self.assertEqual(voice_tag.id, 1)
            self.assertEqual(audio_tag.id, 1)
            self.assertNotEqual(voice_tag.__tablename__, audio_tag.__tablename__)

    def test_service_protects_type_english_value_and_uniqueness(self) -> None:
        with self.session_factory() as session:
            with self.assertRaises(DomainValidationError):
                self.service.create_tag(
                    session,
                    tag_type="gender",  # type: ignore[arg-type]
                    english_value="male",
                )
            for value in (None, "", "   ", "bad:value"):
                with self.subTest(value=value), self.assertRaises(
                    DomainValidationError
                ):
                    self.service.create_tag(
                        session,
                        tag_type=AudioTagType.TOPIC,
                        english_value=value,
                    )

            tag = self.service.create_tag(
                session,
                tag_type=AudioTagType.CATEGORY,
                english_value="Short Answer",
                translations=[
                    TagTranslationInput(language="zh_cn", value="简 答"),
                ],
            )
            session.commit()
            self.assertEqual(tag.value, "Short_Answer")
            self.assertEqual(tag.translations[0].value, "简_答")

            with self.assertRaises(ConflictError):
                self.service.create_tag(
                    session,
                    tag_type=AudioTagType.CATEGORY,
                    english_value="short   answer",
                )

    def test_database_protects_type_english_value_and_uniqueness(self) -> None:
        with self.session_factory() as session:
            session.add(
                AudioTag(
                    type="gender",  # type: ignore[arg-type]
                    value="male",
                    normalized_value="male",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

            session.add(
                AudioTag(
                    type=AudioTagType.AUTHOR,
                    value=None,  # type: ignore[arg-type]
                    normalized_value=None,  # type: ignore[arg-type]
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

            first = AudioTag(
                type=AudioTagType.TOPIC,
                value="Climate",
                normalized_value="climate",
            )
            session.add(first)
            session.flush()
            session.add(
                AudioTag(
                    type=AudioTagType.TOPIC,
                    value="climate",
                    normalized_value="climate",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()

    def test_translation_foreign_key_and_language_uniqueness(self) -> None:
        with self.session_factory() as session:
            tag = AudioTag(
                type=AudioTagType.SPEAKER,
                value="Teacher",
                normalized_value="teacher",
            )
            session.add(tag)
            session.flush()
            session.add_all(
                [
                    AudioTagTranslation(
                        tag_id=tag.id,
                        language="zh-CN",
                        value="教师",
                        normalized_value="教师",
                    ),
                    AudioTagTranslation(
                        tag_id=tag.id,
                        language="zh-CN",
                        value="老师",
                        normalized_value="老师",
                    ),
                ]
            )
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

            session.add(
                AudioTagTranslation(
                    tag_id=999,
                    language="zh-CN",
                    value="缺失",
                    normalized_value="缺失",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()


if __name__ == "__main__":
    unittest.main()
