from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "LISTENING_DEBUG_AUTH_ENABLED": "true",
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
        self.assertTrue(settings.debug_auth_enabled)
        self.assertEqual(settings.cosyvoice_model_dir, Path("/models/cosyvoice"))


if __name__ == "__main__":
    unittest.main()
