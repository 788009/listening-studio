from __future__ import annotations

import re
import time
from uuid import uuid4

from loguru import logger
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id(scope: Scope) -> str:
    supplied = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if supplied and _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _normalized_path(scope: Scope) -> str:
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "<unmatched>"


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        request_logger = logger.bind(request_id=request_id)
        started_at = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_at) * 1000
            request_logger.error(
                "HTTP request failed method={} path={} duration_ms={:.2f} "
                "exception_type={}",
                scope["method"],
                _normalized_path(scope),
                duration_ms,
                type(exc).__name__,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        request_logger.info(
            "HTTP request completed method={} path={} "
            "status_code={} duration_ms={:.2f}",
            scope["method"],
            _normalized_path(scope),
            status_code,
            duration_ms,
        )
