from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.services.paper_rendering import PaperRenderService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class PaperRenderJobHandler:
    def __init__(self, service: PaperRenderService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        paper_id = job.input_summary.get("paperId")
        audio_id = job.input_summary.get("audioId")
        if isinstance(paper_id, bool) or not isinstance(paper_id, int) or paper_id < 1:
            raise JobExecutionError("Paper render task data is invalid")
        if isinstance(audio_id, bool) or not isinstance(audio_id, int) or audio_id < 1:
            raise JobExecutionError("Paper render task data is invalid")
        context.update_progress(5)
        try:
            with context.session_factory() as session:
                audio = self.service.process(
                    session,
                    paper_id=paper_id,
                    audio_id=audio_id,
                    job_id=job.id,
                    owner_id=job.owner_id,
                    request_id=f"job-{job.id}",
                    checkpoint=context.update_progress,
                )
        except JobFailedError as exc:
            raise JobExecutionError("Paper rendering failed") from exc
        context.update_progress(95)
        return JobResult("audio", audio.id)
