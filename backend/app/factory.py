from fastapi import FastAPI

from backend.app.core.errors import install_exception_handlers
from backend.app.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="English Listening Generator")
    install_exception_handlers(app)
    app.include_router(health_router)
    return app
