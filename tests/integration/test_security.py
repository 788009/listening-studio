from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
import wave
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config

from backend.app.core.config import Settings
from backend.app.core.security import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from backend.app.factory import create_app
from backend.app.integrations.identity import (
    DEBUG_ISSUER_HEADER,
    DEBUG_SUBJECT_HEADER,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SecurityIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_dir.name)
        self.database_url = f"sqlite:///{self.root / 'security.sqlite3'}"
        config = Config(PROJECT_ROOT / "alembic.ini")
        config.set_main_option("sqlalchemy.url", self.database_url)
        command.upgrade(config, "head")
        self.settings = self._settings()
        self.app = create_app(self.settings)

    def tearDown(self) -> None:
        self.app.state.db_engine.dispose()
        self.temporary_dir.cleanup()

    def _settings(self, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "_env_file": None,
            "environment": "test",
            "debug_auth_enabled": True,
            "auth_session_secret": "test-session-secret-with-32-characters",
            "cosyvoice_model_dir": self.root / "model",
            "database_url": self.database_url,
            "data_dir": self.root / "data",
            "log_dir": self.root / "logs",
        }
        values.update(overrides)
        return Settings(**values)

    @staticmethod
    def identity_headers(subject: str) -> dict[str, str]:
        return {
            DEBUG_ISSUER_HEADER: "https://issuer.example",
            DEBUG_SUBJECT_HEADER: subject,
        }

    @staticmethod
    def wav_bytes(duration_seconds: float = 1.0) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * int(8000 * duration_seconds))
        return output.getvalue()

    def test_cookie_session_requires_valid_csrf_for_writes(self) -> None:
        async def scenario() -> tuple[httpx.Response, ...]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                login = await client.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("csrf-teacher"),
                )
                csrf = client.cookies.get(CSRF_COOKIE_NAME)
                assert csrf is not None
                missing = await client.post(
                    "/api/users/me/profile",
                    json={"userId": "CsrfTeacher"},
                )
                forged = await client.post(
                    "/api/users/me/profile",
                    headers={CSRF_HEADER_NAME: "forged"},
                    json={"userId": "CsrfTeacher"},
                )
                accepted = await client.post(
                    "/api/users/me/profile",
                    headers={CSRF_HEADER_NAME: csrf},
                    json={"userId": "CsrfTeacher"},
                )
                logout = await client.delete(
                    "/auth/session",
                    headers={CSRF_HEADER_NAME: csrf},
                )
                after_logout = await client.get("/api/users/me")
                return login, missing, forged, accepted, logout, after_logout

        login, missing, forged, accepted, logout, after_logout = asyncio.run(scenario())
        self.assertEqual(login.status_code, 204)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.json()["error"]["code"], "csrf_failed")
        self.assertEqual(forged.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(logout.json(), {"redirectUrl": None})
        self.assertEqual(after_logout.status_code, 401)

    def test_security_headers_and_production_cookie_attributes(self) -> None:
        async def request(app, path: str, **kwargs: object) -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://testserver",
            ) as client:
                return await client.get(path, **kwargs)

        liveness = asyncio.run(request(self.app, "/health/live"))
        self.assertEqual(liveness.headers["x-content-type-options"], "nosniff")
        self.assertEqual(liveness.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", liveness.headers["content-security-policy"])
        self.assertEqual(liveness.headers["cache-control"], "private, no-store")

        dist = self.root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("frontend", encoding="utf-8")
        production = create_app(
            self._settings(environment="production", frontend_dist_dir=dist)
        )

        async def login() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production),
                base_url="https://testserver",
            ) as client:
                return await client.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("production-cookie"),
                )

        try:
            response = asyncio.run(login())
        finally:
            production.state.db_engine.dispose()
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if value.startswith("listening_session="))
        csrf_cookie = next(value for value in cookies if value.startswith(f"{CSRF_COOKIE_NAME}="))
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=lax", session_cookie)
        self.assertIn("Secure", session_cookie)
        self.assertNotIn("HttpOnly", csrf_cookie)
        self.assertEqual(response.headers["strict-transport-security"], "max-age=31536000")

    def test_rate_limits_search_and_playback(self) -> None:
        limited = create_app(
            self._settings(
                login_rate_limit=1,
                search_rate_limit=1,
                upload_rate_limit=1,
                generation_rate_limit=1,
                playback_rate_limit=1,
            )
        )

        async def scenario() -> tuple[httpx.Response, ...]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=limited),
                base_url="http://testserver",
            ) as client:
                first_search = await client.get("/api/audios?q=climate")
                limited_search = await client.get("/api/audios?q=climate")
                first_playback = await client.get("/media/audio/999")
                limited_playback = await client.get("/media/audio/999")
                first_login = await client.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("limited-login"),
                )
                limited_login = await client.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("limited-login"),
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=limited),
                base_url="http://testserver",
                headers=self.identity_headers("limited-write"),
            ) as writer:
                first_upload = await writer.post("/api/voices")
                limited_upload = await writer.post("/api/voices")
                first_generation = await writer.post("/api/audios", json={})
                limited_generation = await writer.post("/api/audios", json={})
            return (
                first_search,
                limited_search,
                first_playback,
                limited_playback,
                first_login,
                limited_login,
                first_upload,
                limited_upload,
                first_generation,
                limited_generation,
            )

        try:
            responses = asyncio.run(scenario())
        finally:
            limited.state.db_engine.dispose()
        first_search, limited_search = responses[0:2]
        first_playback, limited_playback = responses[2:4]
        self.assertEqual(first_search.status_code, 200)
        self.assertEqual(limited_search.status_code, 429)
        self.assertEqual(limited_search.json()["error"]["code"], "rate_limited")
        self.assertEqual(limited_search.headers["x-ratelimit-remaining"], "0")
        self.assertIn("retry-after", limited_search.headers)
        self.assertEqual(first_playback.status_code, 404)
        self.assertEqual(limited_playback.status_code, 429)
        first_login, limited_login = responses[4:6]
        first_upload, limited_upload = responses[6:8]
        first_generation, limited_generation = responses[8:10]
        self.assertEqual(first_login.status_code, 204)
        self.assertEqual(limited_login.status_code, 429)
        self.assertNotEqual(first_upload.status_code, 429)
        self.assertEqual(limited_upload.status_code, 429)
        self.assertNotEqual(first_generation.status_code, 429)
        self.assertEqual(limited_generation.status_code, 429)

    def test_upload_size_mime_filename_html_and_private_id_boundaries(self) -> None:
        oversized_app = create_app(self._settings(max_upload_bytes=32))
        self.addCleanup(oversized_app.state.db_engine.dispose)

        async def oversized() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=oversized_app),
                base_url="http://testserver",
            ) as client:
                await client.post(
                    "/api/users/me/profile",
                    headers=self.identity_headers("chunked-oversized"),
                    json={"userId": "ChunkedOversized"},
                )
                return await client.post(
                    "/api/voices",
                    headers=self.identity_headers("oversized"),
                    data={"title": "Oversized"},
                    files={"file": ("reference.wav", b"x" * 70_000, "audio/wav")},
                )

        oversized_response = asyncio.run(oversized())
        self.assertEqual(oversized_response.status_code, 413)
        self.assertEqual(
            oversized_response.json()["error"]["code"],
            "payload_too_large",
        )

        async def chunked_oversized() -> httpx.Response:
            boundary = "security-boundary"

            async def content():
                yield (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="title"\r\n\r\n'
                    "Chunked\r\n"
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="file"; '
                    'filename="reference.wav"\r\n'
                    "Content-Type: audio/wav\r\n\r\n"
                ).encode()
                yield b"x" * 40_000
                yield b"x" * 40_000
                yield f"\r\n--{boundary}--\r\n".encode()

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=oversized_app),
                base_url="http://testserver",
            ) as client:
                return await client.post(
                    "/api/voices",
                    headers={
                        **self.identity_headers("chunked-oversized"),
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                    },
                    content=content(),
                )

        chunked_response = asyncio.run(chunked_oversized())
        self.assertEqual(chunked_response.status_code, 413)

        private_text = "complete private listening text must not leak"

        async def scenario() -> tuple[httpx.Response, ...]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as owner:
                await owner.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("owner"),
                )
                owner_csrf = owner.cookies.get(CSRF_COOKIE_NAME)
                assert owner_csrf is not None
                await owner.post(
                    "/api/users/me/profile",
                    headers={CSRF_HEADER_NAME: owner_csrf},
                    json={"userId": "SecurityOwner"},
                )
                invalid_mime = await owner.post(
                    "/api/voices",
                    headers={CSRF_HEADER_NAME: owner_csrf},
                    data={"title": "Invalid content"},
                    files={"file": ("../../bad.wav", b"<script>", "audio/wav")},
                )
                created = await owner.post(
                    "/api/voices",
                    headers={CSRF_HEADER_NAME: owner_csrf},
                    data={"title": "<script>alert(1)</script>"},
                    files={"file": ("../../escape.wav", self.wav_bytes(), "text/html")},
                )
                voice_id = created.json()["voiceId"]
                detail = await owner.get(f"/api/voices/{voice_id}")
                private_error = await owner.post(
                    "/api/audios",
                    headers={CSRF_HEADER_NAME: owner_csrf},
                    json={
                        "title": "Private",
                        "text": private_text,
                        "voiceId": 99999,
                        "tagIds": [],
                    },
                )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as other:
                await other.post(
                    "/auth/debug/session",
                    headers=self.identity_headers("other"),
                )
                other_csrf = other.cookies.get(CSRF_COOKIE_NAME)
                assert other_csrf is not None
                await other.post(
                    "/api/users/me/profile",
                    headers={CSRF_HEADER_NAME: other_csrf},
                    json={"userId": "SecurityOther"},
                )
                hidden = await other.get(f"/api/voices/{voice_id}")
            return invalid_mime, created, detail, private_error, hidden

        invalid_mime, created, detail, private_error, hidden = asyncio.run(scenario())
        self.assertEqual(invalid_mime.status_code, 422)
        self.assertEqual(created.status_code, 202)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.headers["content-type"], "application/json")
        self.assertEqual(detail.json()["title"], "<script>alert(1)</script>")
        self.assertEqual(hidden.status_code, 404)
        self.assertFalse((self.root / "escape.wav").exists())
        self.assertNotIn(private_text, private_error.text)
        self.assertNotIn(str(self.root), private_error.text)
        log_text = (self.settings.log_dir / "backend.log").read_text(encoding="utf-8")
        self.assertNotIn(private_text, log_text)
        self.assertNotIn("listening_session=", log_text)


if __name__ == "__main__":
    unittest.main()
