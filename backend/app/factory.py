from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from backend.app.api.auth import router as auth_router
from backend.app.api.audios import media_router as audio_media_router
from backend.app.api.audios import router as audios_router
from backend.app.api.audio_previews import media_router as audio_preview_media_router
from backend.app.api.audio_previews import (
    publish_router as audio_preview_publish_router,
)
from backend.app.api.audio_previews import router as audio_previews_router
from backend.app.api.generation_batches import router as generation_batches_router
from backend.app.api.jobs import router as jobs_router
from backend.app.api.papers import paper_router, preset_router
from backend.app.api.resource_management import router as resource_management_router
from backend.app.api.tags import audio_router as audio_tags_router
from backend.app.api.tags import voice_router as voice_tags_router
from backend.app.api.users import router as users_router
from backend.app.api.voices import media_router as voice_media_router
from backend.app.api.voices import router as voices_router
from backend.app.core.auth import AuthenticationMiddleware
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import install_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.request_logging import RequestLoggingMiddleware
from backend.app.core.security import SecurityMiddleware
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.frontend import install_frontend
from backend.app.health import router as health_router
from backend.app.integrations.identity import (
    IdentityProvider,
    PlaceholderIdentityProvider,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Application started")
    try:
        yield
    finally:
        app.state.db_engine.dispose()
        logger.info("Application stopped")


def create_app(
    settings: Settings | None = None,
    identity_provider: IdentityProvider | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    engine = create_db_engine(settings.database_url)

    app = FastAPI(title="English Listening Generator", lifespan=lifespan)
    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.identity_provider = identity_provider or PlaceholderIdentityProvider(
        settings
    )
    install_exception_handlers(app)
    app.add_middleware(
        AuthenticationMiddleware,
        identity_provider=app.state.identity_provider,
        session_factory=app.state.session_factory,
    )
    app.add_middleware(
        SecurityMiddleware,
        session_cookie_name=settings.auth_session_cookie_name,
        session_secret=settings.auth_session_secret,
        production=settings.environment == "production",
        max_upload_bytes=settings.max_upload_bytes,
        max_corpus_bytes=settings.max_corpus_bytes,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        login_rate_limit=settings.login_rate_limit,
        search_rate_limit=settings.search_rate_limit,
        upload_rate_limit=settings.upload_rate_limit,
        generation_rate_limit=settings.generation_rate_limit,
        playback_rate_limit=settings.playback_rate_limit,
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(voice_tags_router)
    app.include_router(audio_tags_router)
    app.include_router(voices_router)
    app.include_router(audios_router)
    app.include_router(audio_previews_router)
    app.include_router(audio_preview_publish_router)
    app.include_router(audio_media_router)
    app.include_router(audio_preview_media_router)
    app.include_router(voice_media_router)
    app.include_router(jobs_router)
    app.include_router(generation_batches_router)
    app.include_router(preset_router)
    app.include_router(paper_router)
    app.include_router(resource_management_router)
    app.include_router(health_router)
    if settings.environment == "production":
        install_frontend(app, settings.frontend_dist_dir)
    logger.info("Application initialized")
    return app
