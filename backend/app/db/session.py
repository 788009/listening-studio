from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, event
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool


def create_db_engine(
    database_url: str,
    *,
    poolclass: type[Pool] | None = None,
) -> Engine:
    engine_options: dict[str, Any] = {"pool_pre_ping": True}
    url = make_url(database_url)

    if poolclass is not None:
        engine_options["poolclass"] = poolclass
    if url.get_backend_name() == "sqlite":
        engine_options["connect_args"] = {"check_same_thread": False}

    engine = sqlalchemy_create_engine(database_url, **engine_options)

    if url.get_backend_name() == "sqlite":
        _enable_sqlite_foreign_keys(engine)

    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


async def get_db_session(request: Request) -> AsyncGenerator[Session, None]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
