from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.services.audio_previews import AudioPreviewService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class AudioPreviewJobHandler:
    def __init__(self, service: AudioPreviewService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        digest = job.input_summary.get("contentDigest")
        if not isinstance(digest, str) or len(digest) != 64:
            raise JobExecutionError("Audio preview task data is invalid")
        context.update_progress(5)
        try:
            with context.session_factory() as session:
                self.service.process(
                    session,
                    job_id=job.id,
                    owner_id=job.owner_id,
                    expected_digest=digest,
                    checkpoint=context.update_progress,
                )
        except Exception as exc:
            self.service.job_storage.cleanup(job.id)
            if isinstance(exc, JobFailedError):
                raise JobExecutionError(
                    "Audio preview generation failed. Verify the selected voice and try again."
                ) from exc
            raise
        return JobResult("audio_preview", job.id)
