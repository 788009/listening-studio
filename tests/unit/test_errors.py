from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from collections.abc import Awaitable, Callable
from contextlib import redirect_stderr
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Body
from pydantic import BaseModel
from starlette.types import ASGIApp

from backend.app.api.schemas import ResourceId
from backend.app.core.config import Settings
from backend.app.core.exceptions import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ForbiddenError,
    JobFailedError,
    NotFoundError,
)
from backend.app.factory import create_app


class ResourcePayload(BaseModel):
    resource_id: ResourceId


def domain_error_endpoint(
    error_type: type[DomainError],
) -> Callable[[], Awaitable[None]]:
    async def raise_domain_error() -> None:
        raise error_type(details={"field": "value"})

    return raise_domain_error


class ErrorHandlingTest(unittest.TestCase):
    @staticmethod
    async def request(
        app: ASGIApp,
        method: str,
        path: str,
        **kwargs: object,
    ) -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    @staticmethod
    def settings(root: Path) -> Settings:
        return Settings(
            _env_file=None,
            cosyvoice_model_dir=root / "model",
            database_url=f"sqlite:///{root / 'test.sqlite3'}",
            data_dir=root / "data",
            log_dir=root / "logs",
        )

    def test_domain_errors_map_to_stable_status_and_code(self) -> None:
        error_cases = [
            (NotFoundError, 404, "not_found"),
            (ForbiddenError, 403, "forbidden"),
            (ConflictError, 409, "conflict"),
            (DomainValidationError, 422, "validation_error"),
            (JobFailedError, 500, "job_failed"),
        ]

        with tempfile.TemporaryDirectory() as temporary_dir:
            app = create_app(self.settings(Path(temporary_dir)))

            for index, (error_type, _, _) in enumerate(error_cases):
                app.add_api_route(
                    f"/domain-error-{index}",
                    domain_error_endpoint(error_type),
                    methods=["GET"],
                )

            for index, (_, status_code, code) in enumerate(error_cases):
                with self.subTest(code=code):
                    response = asyncio.run(
                        self.request(
                            app,
                            "GET",
                            f"/domain-error-{index}",
                            headers={"X-Request-ID": f"domain-{index}"},
                        )
                    )
                    payload = response.json()["error"]
                    self.assertEqual(response.status_code, status_code)
                    self.assertEqual(payload["code"], code)
                    self.assertEqual(payload["details"], {"field": "value"})
                    self.assertEqual(payload["request_id"], f"domain-{index}")

    def test_request_validation_uses_sanitized_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            app = create_app(self.settings(Path(temporary_dir)))

            @app.post("/validate")
            async def validate(payload: Annotated[ResourcePayload, Body()]) -> None:
                del payload

            response = asyncio.run(
                self.request(
                    app,
                    "POST",
                    "/validate",
                    headers={"X-Request-ID": "validation-request"},
                    json={"resource_id": "private-invalid-value"},
                )
            )

        error = response.json()["error"]
        self.assertEqual(response.status_code, 422)
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(error["request_id"], "validation-request")
        self.assertEqual(error["details"][0]["location"], ["body", "resource_id"])
        self.assertNotIn("private-invalid-value", response.text)

    def test_unexpected_error_is_logged_without_leaking_to_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            terminal = io.StringIO()
            with redirect_stderr(terminal):
                app = create_app(self.settings(root))

                @app.get("/unexpected")
                async def unexpected() -> None:
                    raise RuntimeError("/private/path/traceback-secret")

                response = asyncio.run(
                    self.request(
                        app,
                        "GET",
                        "/unexpected",
                        headers={"X-Request-ID": "unexpected-request"},
                    )
                )

            file_log = (root / "logs" / "backend.log").read_text(encoding="utf-8")

        error = response.json()["error"]
        self.assertEqual(response.status_code, 500)
        self.assertEqual(error["code"], "internal_error")
        self.assertIsNone(error["details"])
        self.assertEqual(error["request_id"], "unexpected-request")
        self.assertNotIn("private/path", response.text)
        self.assertNotIn("traceback", response.text.lower())
        self.assertIn("exception_type=RuntimeError", terminal.getvalue())
        self.assertIn("exception_type=RuntimeError", file_log)


if __name__ == "__main__":
    unittest.main()
