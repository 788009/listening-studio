from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx
from starlette.types import ASGIApp

from backend.app.core.config import Settings
from backend.app.factory import create_app


class FrontendIntegrationTest(unittest.TestCase):
    @staticmethod
    def settings(root: Path) -> Settings:
        return Settings(
            _env_file=None,
            environment="production",
            cosyvoice_model_dir=root / "model",
            database_url=f"sqlite:///{root / 'test.sqlite3'}",
            data_dir=root / "data",
            log_dir=root / "logs",
            frontend_dist_dir=root / "dist",
        )

    @staticmethod
    def request(app: ASGIApp, path: str) -> httpx.Response:
        async def send_request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get(path)

        return asyncio.run(send_request())

    def test_production_serves_assets_and_frontend_route_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            dist_dir = root / "dist"
            assets_dir = dist_dir / "assets"
            assets_dir.mkdir(parents=True)
            (dist_dir / "index.html").write_text(
                "<html><body>frontend shell</body></html>", encoding="utf-8"
            )
            (assets_dir / "app.js").write_text("export {}", encoding="utf-8")
            (root / "secret.txt").write_text("secret", encoding="utf-8")
            app = create_app(self.settings(root))

            route_response = self.request(app, "/library/example")
            asset_response = self.request(app, "/assets/app.js")
            traversal_response = self.request(app, "/assets/%2e%2e/secret.txt")

        self.assertEqual(route_response.status_code, 200)
        self.assertIn("frontend shell", route_response.text)
        self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(asset_response.text, "export {}")
        self.assertEqual(traversal_response.status_code, 404)
        self.assertNotIn("secret", traversal_response.text)

    def test_protected_backend_prefixes_do_not_use_spa_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            dist_dir = root / "dist"
            dist_dir.mkdir()
            (dist_dir / "index.html").write_text("frontend shell", encoding="utf-8")
            app = create_app(self.settings(root))

            for prefix in ("api", "auth", "health", "media"):
                with self.subTest(prefix=prefix):
                    response = self.request(app, f"/{prefix}/missing")
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn("frontend shell", response.text)
                    self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_production_requires_a_frontend_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings = self.settings(Path(temporary_dir))

            with self.assertRaisesRegex(
                RuntimeError, "Production frontend build is missing"
            ):
                create_app(settings)


if __name__ == "__main__":
    unittest.main()
