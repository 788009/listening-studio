from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


_EXCLUDED_ROOTS = {"api", "auth", "health", "media"}


def _safe_file(dist_dir: Path, relative_path: str) -> Path | None:
    candidate = (dist_dir / relative_path).resolve()
    if not candidate.is_relative_to(dist_dir) or not candidate.is_file():
        return None
    return candidate


def install_frontend(app: FastAPI, configured_dist_dir: Path) -> None:
    dist_dir = configured_dist_dir.resolve()
    index_path = dist_dir / "index.html"
    if not index_path.is_file():
        raise RuntimeError("Production frontend build is missing")
    index_content = index_path.read_bytes()

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def serve_frontend(request: Request, full_path: str) -> Response:
        root_segment = full_path.partition("/")[0]
        if root_segment in _EXCLUDED_ROOTS:
            raise HTTPException(status_code=404, detail="Not Found")

        requested_file = _safe_file(dist_dir, full_path)
        if requested_file is None and root_segment == "assets":
            raise HTTPException(status_code=404, detail="Not Found")

        content = requested_file.read_bytes() if requested_file else index_content
        media_type = (
            mimetypes.guess_type(requested_file.name)[0]
            if requested_file
            else "text/html"
        )
        headers = {
            "Content-Length": str(len(content)),
            "Cache-Control": (
                "public, max-age=31536000, immutable"
                if root_segment == "assets"
                else "no-cache"
            ),
        }
        return Response(
            content=b"" if request.method == "HEAD" else content,
            media_type=media_type,
            headers=headers,
        )
