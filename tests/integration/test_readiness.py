from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from backend.app.core.config import Settings
from backend.app.factory import create_app


class ReadinessIntegrationTest(unittest.TestCase):
    @staticmethod
    def request(settings: Settings) -> httpx.Response:
        async def send_request() -> httpx.Response:
            transport = httpx.ASGITransport(app=create_app(settings))
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get(
                    "/health/ready",
                    headers={"X-Request-ID": "readiness-request"},
                )

        return asyncio.run(send_request())

    def test_readiness_checks_temporary_database_and_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            settings = Settings(
                _env_file=None,
                cosyvoice_model_dir=root / "model",
                database_url=f"sqlite:///{root / 'test.sqlite3'}",
                data_dir=root / "data",
                log_dir=root / "logs",
            )

            response = self.request(settings)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        self.assertEqual(response.headers["X-Request-ID"], "readiness-request")

    def test_unavailable_database_returns_503_and_logs_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            settings = Settings(
                _env_file=None,
                cosyvoice_model_dir=root / "model",
                database_url=f"sqlite:///{root / 'missing' / 'test.sqlite3'}",
                data_dir=root / "data",
                log_dir=root / "logs",
            )

            response = self.request(settings)
            log_text = (root / "logs" / "backend.log").read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["X-Request-ID"], "readiness-request")
        self.assertEqual(
            response.json(),
            {"error": {"code": "http_503", "message": "Service not ready"}},
        )
        self.assertIn("request_id=readiness-request", log_text)
        self.assertIn("Readiness check failed component=database", log_text)


if __name__ == "__main__":
    unittest.main()
