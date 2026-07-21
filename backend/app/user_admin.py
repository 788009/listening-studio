from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from loguru import logger

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.repositories.users import UserRepository
from backend.app.services.users import UserService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage backend-only teacher account permissions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("set-super-admin", "Grant Super Admin to a teacher account."),
        ("unset-super-admin", "Revoke Super Admin and restore User."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument(
            "user_id",
            metavar="USER_ID",
            help="Completed teacher user ID; matching is case-insensitive.",
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
            user = UserRepository().get_by_user_id(session, arguments.user_id)
            if user is None or user.user_id is None:
                logger.warning(
                    "Teacher role command failed command={} user_id={} reason=not_found",
                    arguments.command,
                    arguments.user_id,
                )
                print(
                    f"Teacher account not found: {arguments.user_id}",
                    file=sys.stderr,
                )
                return 1

            enabled = arguments.command == "set-super-admin"
            previous_role = user.role
            UserService().set_super_admin(session, user, enabled=enabled)
            session.commit()
            logger.bind(
                user_db_id=user.id,
                resource_type="user",
                resource_id=user.id,
            ).info(
                "Teacher role changed command={} user_id={} previous_role={} role={} changed={}",
                arguments.command,
                user.user_id,
                previous_role.value,
                user.role.value,
                previous_role is not user.role,
            )
            print(
                json.dumps(
                    {
                        "userId": user.user_id,
                        "previousRole": previous_role.value,
                        "role": user.role.value,
                        "changed": previous_role is not user.role,
                    }
                )
            )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
