from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from loguru import logger

from backend.app.core.config import Settings


LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
    "request_id={extra[request_id]} | {message}"
)


def _retain_newest(max_files: int) -> Callable[[Iterable[str]], None]:
    def retention(log_files: Iterable[str]) -> None:
        paths = sorted(
            (Path(log_file) for log_file in log_files),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths[max_files:]:
            path.unlink(missing_ok=True)

    return retention


def configure_logging(settings: Settings) -> Path:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = settings.log_dir / "backend.log"

    logger.remove()
    logger.configure(extra={"request_id": "-"})
    logger.add(
        sys.stderr,
        level="INFO",
        format=LOG_FORMAT,
        backtrace=False,
        diagnose=False,
    )
    logger.add(
        log_path,
        level="DEBUG",
        format=LOG_FORMAT,
        rotation=settings.log_rotation_bytes,
        retention=_retain_newest(settings.log_retention_files),
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
    )
    return log_path
