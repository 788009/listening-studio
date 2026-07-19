from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.db.models.voice import VoiceVisibility
from backend.app.services.voice_uploads import VoiceUploadService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class VoiceUploadJobHandler:
    def __init__(self, service: VoiceUploadService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        voice_id = job.input_summary.get("voiceId")
        visibility_value = job.input_summary.get("targetVisibility")
        if (
            isinstance(voice_id, bool)
            or not isinstance(voice_id, int)
            or voice_id < 1
        ):
            raise JobExecutionError("Voice upload task data is invalid")
        try:
            visibility = VoiceVisibility(visibility_value)
        except (TypeError, ValueError):
            raise JobExecutionError("Voice upload visibility is invalid") from None

        context.update_progress(5)
        try:
            with context.session_factory() as session:
                voice = self.service.process_async_upload(
                    session,
                    voice_id=voice_id,
                    job_id=job.id,
                    target_visibility=visibility,
                    request_id=f"job-{job.id}",
                    checkpoint=context.update_progress,
                )
        except JobFailedError as exc:
            raise JobExecutionError(
                "Voice generation failed. Verify the reference WAV and try again."
            ) from exc
        context.update_progress(95)
        return JobResult("voice", voice.id)
