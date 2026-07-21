from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

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
            self.assertEqual(revision, "20260721_0018")

            command.downgrade(config, "base")
            with engine.connect() as connection:
                revision = MigrationContext.configure(connection).get_current_revision()
            engine.dispose()

        self.assertIsNone(revision)

    def test_user_role_migration_defaults_existing_and_new_users(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "user-roles.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260720_0017")
            engine = create_db_engine(database_url)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(issuer, subject, status, user_id, normalized_user_id) "
                        "VALUES ('issuer', 'existing', 'active', "
                        "'ExistingUser', 'existinguser')"
                    )
                )

            command.upgrade(config, "head")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(issuer, subject, status, user_id, normalized_user_id) "
                        "VALUES ('issuer', 'new', 'active', 'NewUser', 'newuser')"
                    )
                )
                roles = connection.execute(
                    text("SELECT user_id, role FROM users ORDER BY id")
                ).all()
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text("UPDATE users SET role = 'invalid' WHERE id = 1")
                    )
            command.downgrade(config, "20260720_0017")
            with engine.connect() as connection:
                columns = {
                    column["name"]
                    for column in inspect(connection).get_columns("users")
                }
            engine.dispose()

        self.assertEqual(roles, [("ExistingUser", "user"), ("NewUser", "user")])
        self.assertNotIn("role", columns)

    def test_sqlite_connections_enable_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "foreign-keys.sqlite3"
            engine = create_db_engine(f"sqlite:///{database_path}")
            with engine.connect() as connection:
                foreign_keys_enabled = connection.scalar(text("PRAGMA foreign_keys"))
            engine.dispose()

        self.assertEqual(foreign_keys_enabled, 1)

    def test_batch_question_type_count_migration_preserves_legacy_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "batch-counts.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260719_0015")
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
                        "INSERT INTO jobs (owner_id, type, input_summary) "
                        "VALUES (1, 'corpus_generation', '{}')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO generation_batches "
                        "(owner_id, job_id, question_types, requested_count) "
                        "VALUES (1, 1, "
                        "'[\"short_dialogue\", \"monologue\"]', 5)"
                    )
                )

            command.upgrade(config, "head")
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT question_type, requested_count, position "
                        "FROM generation_batch_question_types "
                        "ORDER BY position"
                    )
                ).all()
                columns = {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "generation_batches"
                    )
                }
            self.assertEqual(
                rows,
                [("short_dialogue", 3, 0), ("monologue", 2, 1)],
            )
            self.assertNotIn("question_types", columns)
            self.assertNotIn("requested_count", columns)

            command.downgrade(config, "20260719_0015")
            with engine.connect() as connection:
                legacy_types, legacy_count = connection.execute(
                    text(
                        "SELECT question_types, requested_count "
                        "FROM generation_batches"
                    )
                ).one()
            engine.dispose()

        self.assertEqual(json.loads(legacy_types), ["short_dialogue", "monologue"])
        self.assertEqual(legacy_count, 5)

    def test_question_type_tag_migration_backfills_existing_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "question-type-tags.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260720_0016")
            engine = create_db_engine(database_url)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO audio_tags (type, value, normalized_value) VALUES "
                        "('category', 'short', 'short'), "
                        "('category', 'long', 'long')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audio_tag_translations "
                        "(tag_id, language, value, normalized_value) "
                        "SELECT id, 'zh-CN', '自定义长对话', '自定义长对话' "
                        "FROM audio_tags WHERE normalized_value = 'long'"
                    )
                )

            command.upgrade(config, "head")
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT tags.normalized_value, translations.value "
                        "FROM audio_tags AS tags "
                        "JOIN audio_tag_translations AS translations "
                        "ON translations.tag_id = tags.id "
                        "WHERE tags.type = 'category' "
                        "AND tags.normalized_value IN "
                        "('short', 'long', 'monologue') "
                        "AND translations.language = 'zh-CN' "
                        "ORDER BY tags.normalized_value"
                    )
                ).all()
            engine.dispose()

        self.assertEqual(
            rows,
            [
                ("long", "自定义长对话"),
                ("short", "短对话"),
            ],
        )

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

    def test_voice_deletion_migration_preserves_utterance_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "voice-history.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260716_0011")
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
                        "INSERT INTO voices "
                        "(author_id, title, normalized_title, sample_source) "
                        "VALUES (1, 'Current', 'current', 'original')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audios "
                        "(author_id, title, normalized_title, text, source_type) "
                        "VALUES (1, 'Audio', 'audio', 'Text', 'single_speaker')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audio_utterances "
                        "(audio_id, voice_id, speaker_display_name, text, position) "
                        "VALUES (1, 1, 'Historical', 'Text', 0)"
                    )
                )

            command.upgrade(config, "head")
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM voices WHERE id = 1"))
                history = connection.execute(
                    text(
                        "SELECT voice_id, speaker_display_name "
                        "FROM audio_utterances"
                    )
                ).one()
                voice_id_column = next(
                    column
                    for column in inspect(connection).get_columns("audio_utterances")
                    if column["name"] == "voice_id"
                )
            self.assertEqual(history, (None, "Current"))
            self.assertTrue(voice_id_column["nullable"])

            with self.assertRaisesRegex(
                RuntimeError,
                "deleted-voice utterance history",
            ):
                command.downgrade(config, "20260716_0011")
            with engine.connect() as connection:
                preserved_history = connection.execute(
                    text(
                        "SELECT voice_id, speaker_display_name "
                        "FROM audio_utterances"
                    )
                ).one()
            engine.dispose()

        self.assertEqual(preserved_history, (None, "Current"))

    def test_audio_voice_tag_migration_preserves_existing_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            database_path = Path(temporary_dir) / "audio-voice-tags.sqlite3"
            database_url = f"sqlite:///{database_path}"
            config = Config(PROJECT_ROOT / "alembic.ini")
            config.set_main_option("sqlalchemy.url", database_url)
            command.upgrade(config, "20260719_0013")
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
                        "VALUES (1, 'Audio', 'audio', 'Text', 'single_speaker')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audio_tags "
                        "(type, value, normalized_value) "
                        "VALUES ('speaker', 'Anzu', 'anzu')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audio_tag_associations (audio_id, tag_id) "
                        "VALUES (1, 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO audio_tag_translations "
                        "(tag_id, language, value, normalized_value) "
                        "VALUES (1, 'zh-CN', '安祖', '安祖')"
                    )
                )

            command.upgrade(config, "head")
            with engine.connect() as connection:
                migrated = connection.execute(
                    text(
                        "SELECT audio_tags.type, audio_tags.value, "
                        "audio_tag_translations.value "
                        "FROM audio_tags "
                        "JOIN audio_tag_associations "
                        "ON audio_tag_associations.tag_id = audio_tags.id "
                        "JOIN audio_tag_translations "
                        "ON audio_tag_translations.tag_id = audio_tags.id"
                    )
                ).one()
            self.assertEqual(migrated, ("voice", "Anzu", "安祖"))

            command.downgrade(config, "20260719_0013")
            with engine.connect() as connection:
                restored = connection.scalar(text("SELECT type FROM audio_tags"))
            engine.dispose()

        self.assertEqual(restored, "speaker")


if __name__ == "__main__":
    unittest.main()
