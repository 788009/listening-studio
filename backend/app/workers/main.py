from __future__ import annotations

import signal
from threading import Event

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.integrations.cosyvoice import CosyVoiceAdapter
from backend.app.integrations.llm import (
    PlaceholderListeningContentGenerator,
    ValidatingListeningContentGenerator,
)
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import CORPUS_GENERATION_JOB_TYPE
from backend.app.services.job_storage import JobStorage
from backend.app.services.paper_rendering import (
    PAPER_RENDER_JOB_TYPE,
    PaperRenderService,
)
from backend.app.services.voice_storage import VoiceStorage
from backend.app.services.voice_uploads import (
    VOICE_UPLOAD_JOB_TYPE,
    VoiceUploadService,
)
from backend.app.workers.audio_synthesis import AudioSynthesisJobHandler
from backend.app.workers.corpus_generation import CorpusGenerationJobHandler
from backend.app.workers.jobs import JobHandler, JobWorker
from backend.app.workers.paper_rendering import PaperRenderJobHandler
from backend.app.workers.voice_upload import VoiceUploadJobHandler


def build_handlers(settings: Settings) -> dict[str, JobHandler]:
    integration = CosyVoiceAdapter(settings.cosyvoice_model_dir)
    voice_storage = VoiceStorage(settings.data_dir)
    audio_storage = AudioStorage(settings.data_dir)
    voice_service = VoiceUploadService(
        storage=voice_storage,
        max_upload_bytes=settings.max_upload_bytes,
        integration=integration,
        job_storage=JobStorage(settings.data_dir),
    )
    audio_service = AudioSynthesisService(
        audio_storage=audio_storage,
        voice_storage=voice_storage,
        integration=integration,
    )
    corpus_service = CorpusGenerationService(
        generator=ValidatingListeningContentGenerator(
            PlaceholderListeningContentGenerator()
        ),
        corpus_storage=CorpusStorage(settings.data_dir),
        synthesis_service=audio_service,
        voice_storage=voice_storage,
        silence_milliseconds=settings.dialogue_silence_milliseconds,
    )
    return {
        VOICE_UPLOAD_JOB_TYPE: VoiceUploadJobHandler(voice_service),
        AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(audio_service),
        CORPUS_GENERATION_JOB_TYPE: CorpusGenerationJobHandler(corpus_service),
        PAPER_RENDER_JOB_TYPE: PaperRenderJobHandler(PaperRenderService(audio_storage)),
    }


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
            build_handlers(settings),
            job_storage=JobStorage(settings.data_dir),
        ).run_forever(stop_event)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
