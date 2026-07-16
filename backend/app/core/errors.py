from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from backend.app.core.exceptions import DomainError, ErrorDetails
from backend.app.core.locales import localize_error_message, request_locale
from backend.app.core.request_logging import REQUEST_ID_HEADER


class ErrorContent(BaseModel):
    code: str
    message: str
    details: Any | None
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorContent


_HTTP_ERROR_CODES = {
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
}


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: ErrorDetails = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _get_request_id(request)
    localized_message = localize_error_message(
        request_locale(request),
        code,
        message,
    )
    payload = ErrorResponse(
        error=ErrorContent(
            code=code,
            message=localized_message,
            details=details,
            request_id=request_id,
        )
    )
    response = JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    if headers:
        response.headers.update(headers)
    return response


def _validation_details(exc: RequestValidationError) -> list[object]:
    return [
        {
            "location": list(error["loc"]),
            "type": error["type"],
        }
        for error in exc.errors()
    ]


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(
        request: Request, exc: DomainError
    ) -> JSONResponse:
        return error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            exc.details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        code = _HTTP_ERROR_CODES.get(exc.status_code, f"http_{exc.status_code}")
        return error_response(
            request,
            exc.status_code,
            code,
            message,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request,
            422,
            "validation_error",
            "Request validation failed",
            _validation_details(exc),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return error_response(
            request,
            500,
            "internal_error",
            "Internal server error",
        )
