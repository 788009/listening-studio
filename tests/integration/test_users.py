from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.repositories.users import UserRepository
from backend.app.services.users import UserService


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UserIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_dir.name) / "users.sqlite3"
        database_url = f"sqlite:///{database_path}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.engine = create_db_engine(database_url)
        self.session_factory = create_session_factory(self.engine)
        self.service = UserService()

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_dir.cleanup()

    def test_first_user_has_id_one_and_pending_status(self) -> None:
        with self.session_factory() as session:
            user = self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-1",
            )
            session.commit()

            self.assertEqual(user.id, 1)
            self.assertFalse(user.is_profile_complete)
            self.assertIsNone(user.user_id)

    def test_duplicate_identity_is_rejected_by_service_and_database(self) -> None:
        with self.session_factory() as session:
            self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-1",
            )
            session.commit()

            with self.assertRaises(ConflictError):
                self.service.create_pending_user(
                    session,
                    issuer="https://issuer.example",
                    subject="teacher-1",
                )

        repository = UserRepository()
        with self.session_factory() as session:
            with self.assertRaises(IntegrityError):
                repository.create_pending(
                    session,
                    issuer="https://issuer.example",
                    subject="teacher-1",
                    locale="en",
                )

    def test_user_id_is_case_insensitively_unique_and_immutable(self) -> None:
        with self.session_factory() as session:
            first = self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-1",
            )
            second = self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-2",
            )
            self.service.set_user_id(session, first, "TeacherOne")
            session.commit()

            self.assertEqual(first.normalized_user_id, "teacherone")
            self.assertTrue(first.is_profile_complete)
            with self.assertRaises(ConflictError):
                self.service.set_user_id(session, first, "AnotherId")
            with self.assertRaises(ConflictError):
                self.service.set_user_id(session, second, "teacherone")

    def test_username_can_be_repeated(self) -> None:
        with self.session_factory() as session:
            first = self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-1",
            )
            second = self.service.create_pending_user(
                session,
                issuer="https://issuer.example",
                subject="teacher-2",
            )
            self.service.update_username(session, first, "Shared Name")
            self.service.update_username(session, second, "Shared Name")
            session.commit()

            self.assertEqual(first.username, second.username)
            self.service.update_username(session, first, "Updated Name")
            session.commit()
            self.assertEqual(first.username, "Updated Name")

    def test_user_id_accepts_only_ascii_letters_and_numbers(self) -> None:
        invalid_values = ["", "with space", "teacher-name", "教师", "a" * 65]

        for index, value in enumerate(invalid_values):
            with self.subTest(value=value), self.session_factory() as session:
                user = self.service.create_pending_user(
                    session,
                    issuer="https://issuer.example",
                    subject=f"teacher-{index}",
                )
                with self.assertRaises(DomainValidationError):
                    self.service.set_user_id(session, user, value)
                session.rollback()


if __name__ == "__main__":
    unittest.main()
