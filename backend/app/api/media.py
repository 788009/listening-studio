from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from backend.app.core.exceptions import ConflictError, NotFoundError


def stream_wav(
    request: Request,
    path: Path,
    *,
    cache_control: str,
) -> StreamingResponse:
    if not path.is_file():
        raise NotFoundError("Audio file not found")
    size = path.stat().st_size
    if size == 0:
        raise ConflictError("Audio file is empty")
    start, end, partial = _parse_range(request.headers.get("range"), size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": cache_control,
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _file_range(path, start, end),
        status_code=206 if partial else 200,
        media_type="audio/wav",
        headers=headers,
    )


def _parse_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if value is None:
        return 0, size - 1, False
    try:
        unit, specification = value.split("=", maxsplit=1)
        if unit.casefold() != "bytes" or "," in specification:
            raise ValueError
        start_value, end_value = specification.split("-", maxsplit=1)
        if not start_value:
            length = int(end_value)
            if length <= 0:
                raise ValueError
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_value)
            end = int(end_value) if end_value else size - 1
            if start < 0 or start >= size or end < start:
                raise ValueError
            end = min(end, size - 1)
        return start, end, True
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=416,
            detail="Requested range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        ) from None


async def _file_range(path: Path, start: int, end: int) -> AsyncIterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as source:
        source.seek(start)
        while remaining:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
