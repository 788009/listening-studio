from __future__ import annotations

import signal
from threading import Event

from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.workers.jobs import JobHandler, JobWorker


def build_handlers() -> dict[str, JobHandler]:
    return {}


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_db_engine(settings.database_url)
    stop_event = Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        JobWorker(
            create_session_factory(engine),
            build_handlers(),
        ).run_forever(stop_event)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
