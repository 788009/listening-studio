from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.db.models.audio import AudioVisibility
from backend.app.services.assemblies import AssemblyService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class AssemblyJobHandler:
    def __init__(self, service: AssemblyService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        audio_id = job.input_summary.get("audioId")
        try:
            visibility = AudioVisibility(job.input_summary.get("targetVisibility"))
        except (TypeError, ValueError):
            raise JobExecutionError("Assembly task visibility is invalid") from None
        if isinstance(audio_id, bool) or not isinstance(audio_id, int) or audio_id < 1:
            raise JobExecutionError("Assembly task data is invalid")
        context.update_progress(5)
        try:
            with context.session_factory() as session:
                audio = self.service.process(
                    session,
                    audio_id=audio_id,
                    job_id=job.id,
                    owner_id=job.owner_id,
                    visibility=visibility,
                    checkpoint=context.update_progress,
                )
        except JobFailedError as exc:
            raise JobExecutionError("Assembly rendering failed") from exc
        context.update_progress(95)
        return JobResult("audio", audio.id)


class AssemblyPreviewJobHandler:
    def __init__(self, service: AssemblyService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        context.update_progress(5)
        try:
            with context.session_factory() as session:
                self.service.process_preview(
                    session,
                    job_id=job.id,
                    owner_id=job.owner_id,
                    checkpoint=context.update_progress,
                )
        except JobFailedError as exc:
            raise JobExecutionError("Assembly preview rendering failed") from exc
        return JobResult("assembly_preview", job.id)
