from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from backend.app.db.session import create_db_engine


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DatabaseIntegrationTest(unittest.TestCase):
    def test_fresh_database_upgrades_and_downgrades_to_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "migration.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)

            command.upgrade(config, "head")
            command.check(config)
            engine = create_db_engine(database_url)
            with engine.connect() as connection:
                revision = MigrationContext.configure(connection).get_current_revision()
            self.assertEqual(revision, "20260716_0011")

            command.downgrade(config, "base")
            with engine.connect() as connection:
                revision = MigrationContext.configure(connection).get_current_revision()
            engine.dispose()

        self.assertIsNone(revision)

    def test_sqlite_connections_enable_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "foreign-keys.sqlite3"
            engine = create_db_engine(f"sqlite:///{database_path}")
            with engine.connect() as connection:
                foreign_keys_enabled = connection.scalar(text("PRAGMA foreign_keys"))
            engine.dispose()

        self.assertEqual(foreign_keys_enabled, 1)

    def test_voice_sample_migration_preserves_existing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "voice-samples.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260716_0006")
            engine = create_db_engine(database_url)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(issuer, subject, status, user_id, normalized_user_id) "
                        "VALUES ('issuer', 'subject', 'active', 'TeacherOne', "
                        "'teacherone')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audios "
                        "(author_id, title, normalized_title, text, source_type) "
                        "VALUES (1, 'Audio', 'audio', 'Text', 'corpus')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO voices "
                        "(author_id, title, normalized_title, example_mode, "
                        "example_audio_id) VALUES "
                        "(1, 'Original', 'original', 'reference', NULL), "
                        "(1, 'Audio', 'audio', 'audio', 1)"
                    )
                )

            command.upgrade(config, "head")
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT sample_source, sample_audio_id FROM voices "
                        "ORDER BY id"
                    )
                ).all()
                columns = {
                    column["name"] for column in inspect(connection).get_columns("voices")
                }
            self.assertEqual(rows, [("original", None), ("public_audio", 1)])
            self.assertIn("sample_audio_id", columns)
            self.assertNotIn("example_audio_id", columns)

            command.downgrade(config, "20260716_0006")
            with engine.connect() as connection:
                restored = connection.execute(
                    text(
                        "SELECT example_mode, example_audio_id FROM voices "
                        "ORDER BY id"
                    )
                ).all()
            engine.dispose()

        self.assertEqual(restored, [("reference", None), ("audio", 1)])


if __name__ == "__main__":
    unittest.main()
