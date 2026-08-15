from __future__ import annotations

import signal
from threading import Event

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.integrations.cosyvoice import CosyVoiceAdapter
from backend.app.integrations.llm import (
    DashScopeLlmIntegration,
    ValidatingListeningContentGenerator,
    ValidatingTopicTagSuggester,
)
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.assemblies import ASSEMBLY_JOB_TYPE, AssemblyService
from backend.app.services.audio_previews import (
    AUDIO_PREVIEW_JOB_TYPE,
    AudioPreviewService,
)
from backend.app.services.audio_synthesis import (
    AUDIO_SYNTHESIS_JOB_TYPE,
    AudioSynthesisService,
)
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.services.corpus_storage import CorpusStorage
from backend.app.services.generation_batches import CORPUS_GENERATION_JOB_TYPE
from backend.app.services.job_storage import ASSEMBLY_PREVIEW_JOB_TYPE, JobStorage
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
from backend.app.workers.assemblies import AssemblyJobHandler, AssemblyPreviewJobHandler
from backend.app.workers.audio_preview import AudioPreviewJobHandler
from backend.app.workers.corpus_generation import CorpusGenerationJobHandler
from backend.app.workers.jobs import JobHandler, JobWorker
from backend.app.workers.paper_rendering import PaperRenderJobHandler
from backend.app.workers.voice_upload import VoiceUploadJobHandler


def build_handlers(settings: Settings) -> dict[str, JobHandler]:
    integration = CosyVoiceAdapter(
        settings.cosyvoice_model_dir,
        vllm_enabled=settings.cosyvoice_vllm_enabled,
        vllm_gpu_memory_utilization=(
            settings.cosyvoice_vllm_gpu_memory_utilization
        ),
        vllm_max_num_seqs=settings.cosyvoice_vllm_max_num_seqs,
    )
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
    audio_preview_service = AudioPreviewService(
        job_storage=JobStorage(settings.data_dir),
        voice_storage=voice_storage,
        integration=integration,
        synthesis_service=audio_service,
    )
    if (
        settings.dashscope_api_key is None
        or not settings.dashscope_base_url
        or not settings.dashscope_model
    ):
        raise RuntimeError(
            "DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, and DASHSCOPE_MODEL are required"
        )
    llm = DashScopeLlmIntegration(
        api_key=settings.dashscope_api_key.get_secret_value(),
        base_url=settings.dashscope_base_url,
        model=settings.dashscope_model,
    )
    corpus_service = CorpusGenerationService(
        generator=ValidatingListeningContentGenerator(llm),
        tag_suggester=ValidatingTopicTagSuggester(llm),
        corpus_storage=CorpusStorage(settings.data_dir),
    )
    return {
        VOICE_UPLOAD_JOB_TYPE: VoiceUploadJobHandler(voice_service),
        AUDIO_SYNTHESIS_JOB_TYPE: AudioSynthesisJobHandler(audio_service),
        AUDIO_PREVIEW_JOB_TYPE: AudioPreviewJobHandler(audio_preview_service),
        CORPUS_GENERATION_JOB_TYPE: CorpusGenerationJobHandler(corpus_service),
        PAPER_RENDER_JOB_TYPE: PaperRenderJobHandler(PaperRenderService(audio_storage)),
        ASSEMBLY_JOB_TYPE: AssemblyJobHandler(AssemblyService(audio_storage)),
        ASSEMBLY_PREVIEW_JOB_TYPE: AssemblyPreviewJobHandler(
            AssemblyService(audio_storage)
        ),
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
            max_concurrency=settings.worker_concurrency,
            job_storage=JobStorage(settings.data_dir),
        ).run_forever(stop_event)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
