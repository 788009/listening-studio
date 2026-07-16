from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User, UserStatus
from backend.app.factory import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
METRICS_TOKEN = "internal-test-token"


class MetricsIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        database_url = f"sqlite:///{self.root / 'metrics.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(config, "head")
        self.settings = Settings(
            _env_file=None,
            environment="test",
            auth_session_secret="test-session-secret-with-32-characters",
            metrics_token=METRICS_TOKEN,
            cosyvoice_model_dir=self.root / "missing-model",
            database_url=database_url,
            data_dir=self.root / "data",
            log_dir=self.root / "logs",
        )
        self.app = create_app(self.settings)
        self._seed_jobs()

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    @staticmethod
    async def request(
        app: FastAPI,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/health/metrics", headers=headers)

    def send(self, headers: dict[str, str] | None = None) -> httpx.Response:
        return asyncio.run(self.request(self.app, headers))

    def _seed_jobs(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.app.state.session_factory() as session:
            user = User(
                issuer="https://private-issuer.example",
                subject="private-subject",
                status=UserStatus.ACTIVE,
                user_id="PrivateTeacher",
                normalized_user_id="privateteacher",
                username="Private Teacher",
            )
            session.add(user)
            session.flush()
            for status, duration in (
                (JobStatus.QUEUED, None),
                (JobStatus.RUNNING, None),
                (JobStatus.SUCCEEDED, 10),
                (JobStatus.FAILED, 20),
                (JobStatus.CANCELLED, 30),
            ):
                session.add(
                    Job(
                        type="private-job-type",
                        owner=user,
                        status=status,
                        input_summary={
                            "title": "Private title",
                            "text": "Private listening text",
                            "credential": "private-credential",
                        },
                        started_at=started if duration is not None else None,
                        finished_at=(
                            started + timedelta(seconds=duration)
                            if duration is not None
                            else None
                        ),
                    )
                )
            session.commit()

    def test_metrics_endpoint_requires_configured_bearer_token(self) -> None:
        self.assertEqual(self.send().status_code, 401)
        self.assertEqual(
            self.send({"Authorization": "Bearer wrong-token"}).status_code,
            401,
        )

        self.app.state.settings.metrics_token = None
        self.assertEqual(
            self.send({"Authorization": f"Bearer {METRICS_TOKEN}"}).status_code,
            404,
        )

    def test_metrics_report_aggregate_job_data_without_loading_model(self) -> None:
        self.app.state.settings.metrics_token = SecretStr(METRICS_TOKEN)
        with patch(
            "backend.app.integrations.cosyvoice.importlib.import_module"
        ) as import_module:
            response = self.send(
                {"Authorization": f"Bearer {METRICS_TOKEN}"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "queue_length": 1,
                "running": 1,
                "succeeded": 1,
                "failed": 1,
                "cancelled": 1,
                "processing_duration": {
                    "count": 3,
                    "total_seconds": 60.0,
                    "average_seconds": 20.0,
                    "maximum_seconds": 30.0,
                },
            },
        )
        import_module.assert_not_called()
        response_text = json.dumps(response.json(), ensure_ascii=False)
        for secret in (
            "Private title",
            "Private listening text",
            "private-credential",
            "PrivateTeacher",
            "Private Teacher",
            "private-subject",
            METRICS_TOKEN,
        ):
            self.assertNotIn(secret, response_text)


if __name__ == "__main__":
    unittest.main()
