from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.db.models.audio import AudioVisibility
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class AudioSynthesisJobHandler:
    def __init__(self, service: AudioSynthesisService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        audio_id = job.input_summary.get("audioId")
        visibility_value = job.input_summary.get("targetVisibility")
        if (
            isinstance(audio_id, bool)
            or not isinstance(audio_id, int)
            or audio_id < 1
        ):
            raise JobExecutionError("Audio synthesis task data is invalid")
        try:
            visibility = AudioVisibility(visibility_value)
        except (TypeError, ValueError):
            raise JobExecutionError(
                "Audio synthesis visibility is invalid"
            ) from None

        progress_steps = iter((20, 80))

        def checkpoint() -> None:
            context.update_progress(next(progress_steps, 90))

        context.update_progress(5)
        try:
            with context.session_factory() as session:
                audio = self.service.process_single_speaker(
                    session,
                    audio_id=audio_id,
                    job_id=job.id,
                    target_visibility=visibility,
                    request_id=f"job-{job.id}",
                    checkpoint=checkpoint,
                )
        except JobFailedError as exc:
            raise JobExecutionError(
                "Audio generation failed. Verify the selected voice and try again."
            ) from exc
        context.update_progress(95)
        return JobResult("audio", audio.id)
