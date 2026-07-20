from __future__ import annotations

from backend.app.core.exceptions import JobFailedError
from backend.app.services.corpus_generation import CorpusGenerationService
from backend.app.workers.jobs import (
    JobContext,
    JobExecutionError,
    JobPayload,
    JobResult,
)


class CorpusGenerationJobHandler:
    def __init__(self, service: CorpusGenerationService) -> None:
        self.service = service

    def __call__(self, context: JobContext, job: JobPayload) -> JobResult:
        batch_id = job.input_summary.get("batchId")
        item_id = job.input_summary.get("itemId")
        if (
            isinstance(batch_id, bool)
            or not isinstance(batch_id, int)
            or batch_id < 1
        ):
            raise JobExecutionError("Corpus generation task data is invalid")
        if item_id is not None and (
            isinstance(item_id, bool)
            or not isinstance(item_id, int)
            or item_id < 1
        ):
            raise JobExecutionError("Corpus generation item data is invalid")

        context.update_progress(5)
        try:
            with context.session_factory() as session:
                batch = self.service.process(
                    session,
                    batch_id=batch_id,
                    job_id=job.id,
                    owner_id=job.owner_id,
                    item_id=item_id,
                    request_id=f"job-{job.id}",
                    checkpoint=context.update_progress,
                )
        except JobFailedError as exc:
            raise JobExecutionError("Corpus draft generation failed") from exc
        context.update_progress(95)
        return JobResult("generation_batch", batch.id)
