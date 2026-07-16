from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.models.voice_tag import (
    VoiceTag,
    VoiceTagTranslation,
    VoiceTagType,
)
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.tag_values import TagTranslationInput
from backend.app.services.voice_tags import VoiceTagService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VoiceTagIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_dir.name) / "voice-tags.sqlite3"
        database_url = f"sqlite:///{database_path}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.service = VoiceTagService()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_dir.cleanup()

    def test_first_tag_id_and_whitespace_normalization(self) -> None:
        with self.session_factory() as session:
            tag = self.service.create_tag(
                session,
                tag_type=VoiceTagType.AUTHOR,
                english_value="  Mary   Jane  ",
                translations=[
                    TagTranslationInput(language="zh_cn", value="玛 丽"),
                ],
            )
            session.commit()

            self.assertEqual(tag.id, 1)
            self.assertEqual(tag.value, "Mary_Jane")
            self.assertEqual(tag.normalized_value, "mary_jane")
            self.assertEqual(tag.translations[0].language, "zh-CN")
            self.assertEqual(tag.translations[0].value, "玛_丽")

    def test_invalid_english_values_are_rejected(self) -> None:
        invalid_values: list[object] = [
            None,
            "",
            "   ",
            "bad:value",
            "has.dot",
            "café",
            "___",
        ]

        with self.session_factory() as session:
            for value in invalid_values:
                with self.subTest(value=value), self.assertRaises(
                    DomainValidationError
                ):
                    self.service.create_tag(
                        session,
                        tag_type=VoiceTagType.GENDER,
                        english_value=value,
                    )

    def test_normalized_tag_and_translation_duplicates_are_rejected(self) -> None:
        with self.session_factory() as session:
            self.service.create_tag(
                session,
                tag_type=VoiceTagType.GENDER,
                english_value="Female Voice",
            )
            session.commit()
            with self.assertRaises(ConflictError):
                self.service.create_tag(
                    session,
                    tag_type=VoiceTagType.GENDER,
                    english_value="female   voice",
                )

            with self.assertRaises(ConflictError):
                self.service.create_tag(
                    session,
                    tag_type=VoiceTagType.AUTHOR,
                    english_value="TeacherOne",
                    translations=[
                        TagTranslationInput(language="zh_cn", value="教师一"),
                        TagTranslationInput(language="zh-CN", value="老师一"),
                    ],
                )

    def test_invalid_translation_values_are_rejected(self) -> None:
        with self.session_factory() as session:
            for value in ("", "   ", "值:一", "***", "value.dot"):
                with self.subTest(value=value), self.assertRaises(
                    DomainValidationError
                ):
                    self.service.create_tag(
                        session,
                        tag_type=VoiceTagType.AUTHOR,
                        english_value="TeacherOne",
                        translations=[
                            TagTranslationInput(language="zh-CN", value=value),
                        ],
                    )

    def test_database_unique_and_foreign_key_constraints(self) -> None:
        with self.session_factory() as session:
            first = VoiceTag(
                type=VoiceTagType.GENDER,
                value="Male",
                normalized_value="male",
            )
            session.add(first)
            session.flush()
            session.add(
                VoiceTag(
                    type=VoiceTagType.GENDER,
                    value="male",
                    normalized_value="male",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()

        with self.session_factory() as session:
            tag = VoiceTag(
                type=VoiceTagType.AUTHOR,
                value="Teacher",
                normalized_value="teacher",
            )
            session.add(tag)
            session.flush()
            session.add_all(
                [
                    VoiceTagTranslation(
                        tag_id=tag.id,
                        language="zh-CN",
                        value="教师",
                        normalized_value="教师",
                    ),
                    VoiceTagTranslation(
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

        with self.session_factory() as session:
            session.add(
                VoiceTagTranslation(
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
