from __future__ import annotations

import asyncio
import sys
import unittest

import httpx

from backend.app.factory import create_app


class ApplicationTest(unittest.TestCase):
    @staticmethod
    def get(path: str) -> httpx.Response:
        async def send_request() -> httpx.Response:
            transport = httpx.ASGITransport(app=create_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get(path)

        return asyncio.run(send_request())

    def test_liveness_endpoint(self) -> None:
        response = self.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_unknown_route_uses_json_error_response(self) -> None:
        response = self.get("/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "not_found",
                    "message": "Not Found",
                    "details": None,
                    "request_id": response.headers["X-Request-ID"],
                }
            },
        )

    def test_application_import_does_not_import_cosyvoice(self) -> None:
        imported_modules = set(sys.modules)

        self.assertFalse(any(name.startswith("voice.CosyVoice") for name in imported_modules))


if __name__ == "__main__":
    unittest.main()
