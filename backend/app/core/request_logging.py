from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware


REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id(request: Request) -> str:
    supplied = request.headers.get(REQUEST_ID_HEADER)
    if supplied and _SAFE_REQUEST_ID.fullmatch(supplied):
        return supplied
    return uuid4().hex


def _normalized_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else "<unmatched>"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        request_logger = logger.bind(request_id=request_id)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_at) * 1000
            request_logger.error(
                "HTTP request failed method={} path={} duration_ms={:.2f} "
                "exception_type={}",
                request.method,
                _normalized_path(request),
                duration_ms,
                type(exc).__name__,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        request_logger.info(
            "HTTP request completed method={} path={} "
            "status_code={} duration_ms={:.2f}",
            request.method,
            _normalized_path(request),
            response.status_code,
            duration_ms,
        )
        return response
