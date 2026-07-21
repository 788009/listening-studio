from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config

from backend.app.core.config import Settings
from backend.app.db.models.user import User, UserRole, UserStatus
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.user_admin import main


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UserAdminCommandIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        root = Path(self.temporary_dir.name)
        self.database_url = f"sqlite:///{root / 'user-admin.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", self.database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            auth_session_secret="test-session-secret-with-32-characters",
            cosyvoice_model_dir=root / "model",
            database_url=self.database_url,
            data_dir=root / "data",
            log_dir=root / "logs",
        )
        engine = create_db_engine(self.database_url)
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            session.add(
                User(
                    issuer="https://issuer.example",
                    subject="teacher",
                    status=UserStatus.ACTIVE,
                    user_id="TeacherOne",
                    normalized_user_id="teacherone",
                    username="Teacher One",
                )
            )
            session.commit()
        engine.dispose()

    def tearDown(self) -> None:
        self.temporary_dir.cleanup()

    def role(self) -> UserRole:
        engine = create_db_engine(self.database_url)
        session_factory = create_session_factory(engine)
        try:
            with session_factory() as session:
                user = session.get(User, 1)
                assert user is not None
                return user.role
        finally:
            engine.dispose()

    def run_command(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(arguments, settings=self.settings)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_sets_and_unsets_super_admin_by_case_insensitive_user_id(self) -> None:
        result, output, error = self.run_command(
            "set-super-admin",
            "teacherone",
        )

        self.assertEqual(result, 0)
        self.assertNotIn("Teacher account not found", error)
        self.assertEqual(self.role(), UserRole.SUPER_ADMIN)
        self.assertEqual(
            json.loads(output),
            {
                "userId": "TeacherOne",
                "previousRole": "user",
                "role": "super_admin",
                "changed": True,
            },
        )

        repeated, repeated_output, _ = self.run_command(
            "set-super-admin",
            "TeacherOne",
        )
        self.assertEqual(repeated, 0)
        self.assertFalse(json.loads(repeated_output)["changed"])

        revoked, revoked_output, _ = self.run_command(
            "unset-super-admin",
            "TeacherOne",
        )
        self.assertEqual(revoked, 0)
        self.assertEqual(self.role(), UserRole.USER)
        self.assertEqual(json.loads(revoked_output)["previousRole"], "super_admin")
        self.assertEqual(json.loads(revoked_output)["role"], "user")

    def test_unknown_user_returns_nonzero_without_changes(self) -> None:
        result, output, error = self.run_command(
            "set-super-admin",
            "MissingTeacher",
        )

        self.assertEqual(result, 1)
        self.assertEqual(output, "")
        self.assertIn("Teacher account not found: MissingTeacher", error)
        self.assertEqual(self.role(), UserRole.USER)


if __name__ == "__main__":
    unittest.main()
