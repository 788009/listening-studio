from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.services.consistency import ConsistencyService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan database and managed files for consistency issues.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply repairs with explicit, deterministic rules.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
) -> int:
    arguments = build_parser().parse_args(argv)
    settings = settings or get_settings()
    configure_logging(settings)
    engine = create_db_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            report = ConsistencyService(settings.data_dir).run(
                session,
                apply=arguments.apply,
            )
            if not arguments.apply:
                session.rollback()
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
