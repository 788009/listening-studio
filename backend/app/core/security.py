from __future__ import annotations

import hashlib
import hmac
import math
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import BinaryIO

from pydantic import SecretStr
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.errors import error_response


CSRF_COOKIE_NAME = "listening_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_LOGIN_PATH = "/auth/debug/session"
_LOGIN_PATHS = {_LOGIN_PATH, "/auth/oidc/login"}
_MULTIPART_OVERHEAD_BYTES = 64 * 1024
_MEMORY_SPOOL_BYTES = 1024 * 1024


def issue_csrf_token(session_token: str, secret: SecretStr) -> str:
    return hmac.new(
        secret.get_secret_value().encode("utf-8"),
        b"csrf\x00" + session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class RateLimitDecision:
    limit: int
    remaining: int
    retry_after: int | None = None


class FixedWindowRateLimiter:
    def __init__(self, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._check_count = 0

    def check(self, bucket: str, client_key: str, limit: int) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        key = (bucket, client_key)
        with self._lock:
            self._check_count += 1
            if self._check_count % 1024 == 0:
                stale_keys = [
                    stored_key
                    for stored_key, stored in self._requests.items()
                    if not stored or stored[-1] <= cutoff
                ]
                for stale_key in stale_keys:
                    self._requests.pop(stale_key, None)
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= limit:
                retry_after = max(1, math.ceil(timestamps[0] + self.window_seconds - now))
                return RateLimitDecision(limit=limit, remaining=0, retry_after=retry_after)
            timestamps.append(now)
            return RateLimitDecision(limit=limit, remaining=limit - len(timestamps))


class SecurityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        session_cookie_name: str,
        session_secret: SecretStr,
        production: bool,
        max_upload_bytes: int,
        max_corpus_bytes: int,
        rate_limit_window_seconds: int,
        login_rate_limit: int,
        search_rate_limit: int,
        upload_rate_limit: int,
        generation_rate_limit: int,
        playback_rate_limit: int,
    ) -> None:
        self.app = app
        self.session_cookie_name = session_cookie_name
        self.session_secret = session_secret
        self.production = production
        self.max_upload_bytes = max_upload_bytes
        self.max_corpus_bytes = max_corpus_bytes
        self.limits = {
            "login": login_rate_limit,
            "search": search_rate_limit,
            "upload": upload_rate_limit,
            "generation": generation_rate_limit,
            "playback": playback_rate_limit,
        }
        self.limiter = FixedWindowRateLimiter(rate_limit_window_seconds)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        rate_headers: dict[str, str] = {}

        async def send_secure(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                self._set_security_headers(headers, scope["path"])
                for name, value in rate_headers.items():
                    headers[name] = value
            await send(message)

        body_limit = self._body_limit(scope["method"], scope["path"])
        if self._csrf_required(request) and not self._valid_csrf(request):
            response = error_response(
                request,
                403,
                "csrf_failed",
                "CSRF validation failed",
            )
            await response(scope, receive, send_secure)
            return

        bucket = self._rate_bucket(request)
        if bucket is not None:
            decision = self.limiter.check(
                bucket,
                self._client_key(request),
                self.limits[bucket],
            )
            rate_headers = {
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": str(decision.remaining),
            }
            if decision.retry_after is not None:
                rate_headers["Retry-After"] = str(decision.retry_after)
                response = error_response(
                    request,
                    429,
                    "rate_limited",
                    "Too many requests",
                )
                await response(scope, receive, send_secure)
                return

        if body_limit is not None and self._content_length(request) > body_limit:
            response = self._payload_too_large_response(request, body_limit)
            await response(scope, receive, send_secure)
            return

        buffered_file: BinaryIO | None = None
        app_receive = receive
        if body_limit is not None:
            app_receive, buffered_file = await self._buffer_request_body(
                receive,
                body_limit,
            )
            if app_receive is None:
                response = self._payload_too_large_response(request, body_limit)
                await response(scope, receive, send_secure)
                return
        try:
            await self.app(scope, app_receive, send_secure)
        finally:
            if buffered_file is not None:
                buffered_file.close()

    def _valid_csrf(self, request: Request) -> bool:
        session_token = request.cookies.get(self.session_cookie_name)
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)
        if not session_token or not cookie_token or not header_token:
            return False
        expected = issue_csrf_token(session_token, self.session_secret)
        return hmac.compare_digest(cookie_token, header_token) and hmac.compare_digest(
            cookie_token,
            expected,
        )

    def _csrf_required(self, request: Request) -> bool:
        return (
            request.method in _UNSAFE_METHODS
            and request.url.path != _LOGIN_PATH
            and self.session_cookie_name in request.cookies
        )

    def _rate_bucket(self, request: Request) -> str | None:
        path = request.url.path
        if path in _LOGIN_PATHS and request.method in {"GET", "POST"}:
            return "login"
        if request.method == "GET" and path.startswith("/media/"):
            return "playback"
        if request.method == "POST" and path == "/api/voices":
            return "upload"
        if request.method == "POST" and self._is_generation_path(path):
            return "generation"
        if request.method == "GET" and self._is_search_request(request):
            return "search"
        return None

    @staticmethod
    def _is_generation_path(path: str) -> bool:
        return (
            path in {
                "/api/audios",
                "/api/audios/dialogues",
                "/api/audios/from-previews",
                "/api/audio-previews",
                "/api/generation-batches",
            }
            or path.endswith("/retry")
            or path.endswith("/render")
        )

    @staticmethod
    def _is_search_request(request: Request) -> bool:
        path = request.url.path
        return path.endswith("/autocomplete") or (
            path in {"/api/audios", "/api/voices"}
            and "q" in request.query_params
        )

    def _body_limit(self, method: str, path: str) -> int | None:
        if method != "POST":
            return None
        if path == "/api/voices":
            return self.max_upload_bytes + _MULTIPART_OVERHEAD_BYTES
        if path == "/api/generation-batches":
            return self.max_corpus_bytes + _MULTIPART_OVERHEAD_BYTES
        return None

    @staticmethod
    async def _buffer_request_body(
        receive: Receive,
        limit: int,
    ) -> tuple[Receive | None, BinaryIO | None]:
        buffered = tempfile.SpooledTemporaryFile(
            max_size=_MEMORY_SPOOL_BYTES,
            mode="w+b",
        )
        received = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                buffered.close()
                return None, None
            if message["type"] != "http.request":
                continue
            body = message.get("body", b"")
            received += len(body)
            if received > limit:
                buffered.close()
                return None, None
            buffered.write(body)
            if not message.get("more_body", False):
                break
        buffered.seek(0)
        sent = 0

        async def receive_buffered() -> Message:
            nonlocal sent
            chunk = buffered.read(64 * 1024)
            sent += len(chunk)
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": sent < received,
            }

        return receive_buffered, buffered

    @staticmethod
    def _payload_too_large_response(request: Request, limit: int):
        return error_response(
            request,
            413,
            "payload_too_large",
            "Request body exceeds the allowed size",
            details={"maxBytes": limit},
        )

    @staticmethod
    def _content_length(request: Request) -> int:
        value = request.headers.get("Content-Length")
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except ValueError:
            return 0

    @staticmethod
    def _client_key(request: Request) -> str:
        return f"client:{request.client.host if request.client else 'unknown'}"

    def _set_security_headers(self, headers: MutableHeaders, path: str) -> None:
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        if path.startswith(("/api/", "/auth/", "/health/")):
            headers.setdefault("Cache-Control", "private, no-store")
        if self.production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
