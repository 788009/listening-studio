from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

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
            self.assertEqual(revision, "20260716_0003")

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


if __name__ == "__main__":
    unittest.main()
