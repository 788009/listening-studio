from fastapi import FastAPI
from loguru import logger

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import install_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.request_logging import RequestLoggingMiddleware
from backend.app.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="English Listening Generator")
    app.state.settings = settings
    install_exception_handlers(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(health_router)
    logger.info("Application initialized")
    return app
