from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi import Request
from loguru import logger

from backend.app.core.config import Settings
from backend.app.core.logging import configure_logging
from backend.app.factory import create_app


class LoggingTest(unittest.TestCase):
    @staticmethod
    def settings(root: Path, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "cosyvoice_model_dir": root / "model",
            "data_dir": root / "data",
            "log_dir": root / "logs",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def test_error_request_reuses_request_id_and_excludes_sensitive_data(self) -> None:
        async def send_request(root: Path) -> httpx.Response:
            app = create_app(self.settings(root))

            @app.post("/test-error")
            async def test_error(request: Request) -> None:
                del request
                raise RuntimeError("private request body")

            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.post(
                    "/test-error?token=private-query",
                    headers={
                        "X-Request-ID": "request-123",
                        "Authorization": "Bearer private-auth",
                        "Cookie": "session=private-cookie",
                    },
                    content="private request body",
                )

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            response = asyncio.run(send_request(root))
            log_text = (root / "logs" / "backend.log").read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["X-Request-ID"], "request-123")
        self.assertIn("request_id=request-123", log_text)
        self.assertIn("path=/test-error", log_text)
        self.assertNotIn("private-auth", log_text)
        self.assertNotIn("private-cookie", log_text)
        self.assertNotIn("private-query", log_text)
        self.assertNotIn("private request body", log_text)

    def test_file_logging_rotates_and_keeps_configured_archive_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            settings = self.settings(
                root,
                log_rotation_bytes=200,
                log_retention_files=2,
            )
            configure_logging(settings)

            for index in range(30):
                logger.debug("rotation test record {} {}", index, "x" * 80)

            log_files = list((root / "logs").glob("backend*.log"))

        self.assertGreaterEqual(len(log_files), 2)
        self.assertLessEqual(len(log_files), 3)


if __name__ == "__main__":
    unittest.main()
