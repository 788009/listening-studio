from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import install_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.request_logging import RequestLoggingMiddleware
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.frontend import install_frontend
from backend.app.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started")
    try:
        yield
    finally:
        app.state.db_engine.dispose()
        logger.info("Application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    engine = create_db_engine(settings.database_url)

    app = FastAPI(title="English Listening Generator", lifespan=lifespan)
    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)
    install_exception_handlers(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    if settings.environment == "production":
        install_frontend(app, settings.frontend_dist_dir)
    logger.info("Application initialized")
    return app
