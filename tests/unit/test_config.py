from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from backend.app.core.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_read_environment_variables(self) -> None:
        environment = {
            "COSYVOICE_MODEL_DIR": "/models/cosyvoice",
            "LISTENING_ENVIRONMENT": "production",
            "LISTENING_DATABASE_URL": "sqlite:///temporary.db",
            "LISTENING_DATA_DIR": "/srv/listening/data",
            "LISTENING_LOG_DIR": "/srv/listening/logs",
            "LISTENING_FRONTEND_DIST_DIR": "/srv/listening/frontend",
            "LISTENING_MAX_UPLOAD_BYTES": "1024",
            "LISTENING_MAX_CORPUS_BYTES": "2048",
            "LISTENING_MAX_BATCH_GENERATION_COUNT": "12",
            "LISTENING_DIALOGUE_SILENCE_MILLISECONDS": "750",
            "LISTENING_DEBUG_AUTH_ENABLED": "true",
            "LISTENING_METRICS_TOKEN": "internal-metrics-token",
        }

        with patch.dict(os.environ, environment, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.database_url, "sqlite:///temporary.db")
        self.assertEqual(settings.environment, "production")
        self.assertEqual(settings.data_dir, Path("/srv/listening/data"))
        self.assertEqual(settings.log_dir, Path("/srv/listening/logs"))
        self.assertEqual(
            settings.frontend_dist_dir, Path("/srv/listening/frontend")
        )
        self.assertEqual(settings.max_upload_bytes, 1024)
        self.assertEqual(settings.max_corpus_bytes, 2048)
        self.assertEqual(settings.max_batch_generation_count, 12)
        self.assertEqual(settings.dialogue_silence_milliseconds, 750)
        self.assertTrue(settings.debug_auth_enabled)
        self.assertEqual(
            settings.metrics_token.get_secret_value() if settings.metrics_token else None,
            "internal-metrics-token",
        )
        self.assertEqual(settings.cosyvoice_model_dir, Path("/models/cosyvoice"))

    def test_auth_session_secret_has_minimum_length(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                cosyvoice_model_dir=Path("/models/cosyvoice"),
                auth_session_secret="too-short",
            )


if __name__ == "__main__":
    unittest.main()
