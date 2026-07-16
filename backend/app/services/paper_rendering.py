from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError, JobFailedError, NotFoundError
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.job import Job
from backend.app.db.models.paper import Paper, PaperStatus
from backend.app.db.models.user import User
from backend.app.repositories.audios import AudioRepository
from backend.app.repositories.papers import PaperRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService
from backend.app.services.jobs import JobService
from backend.app.services.paper_renderer import PaperAudioRenderer


PAPER_RENDER_JOB_TYPE = "paper_render"


@dataclass(frozen=True)
class PaperRenderSubmission:
    paper: Paper
    audio: Audio
    job: Job


class PaperRenderService:
    def __init__(
        self,
        storage: AudioStorage,
        *,
        renderer: PaperAudioRenderer | None = None,
        paper_repository: PaperRepository | None = None,
        audio_repository: AudioRepository | None = None,
        audio_service: AudioService | None = None,
        job_service: JobService | None = None,
    ) -> None:
        self.storage = storage
        self.renderer = renderer or PaperAudioRenderer()
        self.paper_repository = paper_repository or PaperRepository()
        self.audio_repository = audio_repository or AudioRepository()
        self.audio_service = audio_service or AudioService(
            storage,
            self.audio_repository,
        )
        self.job_service = job_service or JobService()

    def prepare(
        self,
        session: Session,
        owner: User,
        paper_id: int,
    ) -> PaperRenderSubmission:
        paper = self.paper_repository.get_paper(session, paper_id)
        if paper is None or paper.owner_id != owner.id:
            raise NotFoundError("Paper not found")
        if paper.status is not PaperStatus.PENDING or paper.result_audio_id is not None:
            raise ConflictError("Paper already has a render task")
        audio: Audio | None = None
        try:
            audio = self.audio_service.create_audio(
                session,
                author=owner,
                title=paper.title,
                source_type=AudioSourceType.ASSEMBLY,
                text=self._combined_text(paper),
            )
            paper.result_audio = audio
            job = self.job_service.create_job(
                session,
                owner=owner,
                job_type=PAPER_RENDER_JOB_TYPE,
                input_summary={"paperId": paper.id, "audioId": audio.id},
                retryable=True,
            )
            session.commit()
            return PaperRenderSubmission(paper, audio, job)
        except Exception:
            session.rollback()
            if audio is not None:
                self.storage.delete_audio(audio.id)
            raise

    def process(
        self,
        session: Session,
        *,
        paper_id: int,
        audio_id: int,
        job_id: int,
        owner_id: int,
        request_id: str,
        checkpoint: Callable[[int], None],
    ) -> Audio:
        paper = self.paper_repository.get_paper(session, paper_id)
        audio = self.audio_repository.get_by_id(session, audio_id)
        if (
            paper is None
            or audio is None
            or paper.owner_id != owner_id
            or audio.author_id != owner_id
            or paper.result_audio_id != audio.id
        ):
            self.storage.cleanup_job(job_id)
            raise JobFailedError("Paper render records are unavailable")
        try:
            if (
                paper.status is PaperStatus.READY
                and audio.status is AudioStatus.READY
                and self.audio_service.is_ready(audio)
            ):
                return audio
            self._validate_sources(paper)
            if paper.status is PaperStatus.PENDING:
                paper.status = PaperStatus.PROCESSING
            elif paper.status is not PaperStatus.PROCESSING:
                raise JobFailedError("Paper cannot be rendered from its current state")
            if audio.status is AudioStatus.PENDING:
                self.audio_service.transition_status(
                    session,
                    audio,
                    AudioStatus.PROCESSING,
                )
            elif audio.status is not AudioStatus.PROCESSING:
                raise JobFailedError("Paper output audio is not renderable")
            session.commit()
            checkpoint(20)
            if not self.storage.exists(audio.id):
                self.renderer.render(
                    [self.storage.path(item.audio_id) for item in paper.items],
                    self.storage.temporary_audio_path(job_id),
                    intro_silence_milliseconds=paper.intro_silence_milliseconds,
                    inter_item_silence_milliseconds=(
                        paper.inter_item_silence_milliseconds
                    ),
                    repeat_count=paper.repeat_count,
                    outro_silence_milliseconds=paper.outro_silence_milliseconds,
                )
                checkpoint(80)
                self.storage.inspect_temporary(job_id)
                self.storage.atomic_replace(audio.id, job_id)
            self.audio_service.record_file_metadata(session, audio)
            self.audio_service.transition_status(session, audio, AudioStatus.READY)
            self.audio_service.set_visibility(
                session,
                audio,
                AudioVisibility.PRIVATE,
            )
            paper.status = PaperStatus.READY
            paper.error_summary = None
            session.commit()
            logger.bind(
                request_id=request_id,
                job_id=job_id,
                user_db_id=owner_id,
                resource_type="paper",
                resource_id=paper.id,
            ).info(
                "Paper rendering completed paper_id={} audio_id={} job_id={}",
                paper.id,
                audio.id,
                job_id,
            )
            return audio
        except Exception as exc:
            self._handle_failure(
                session,
                paper_id=paper.id,
                audio_id=audio.id,
                job_id=job_id,
                request_id=request_id,
                exception=exc,
            )
        finally:
            self.storage.cleanup_job(job_id)

    def _validate_sources(self, paper: Paper) -> None:
        if not paper.items:
            raise JobFailedError("Paper has no source audios")
        for item in paper.items:
            if (
                item.audio.status is not AudioStatus.READY
                or not self.audio_service.is_ready(item.audio)
            ):
                raise JobFailedError("A paper source audio is no longer ready")

    def _handle_failure(
        self,
        session: Session,
        *,
        paper_id: int,
        audio_id: int,
        job_id: int,
        request_id: str,
        exception: Exception,
    ) -> NoReturn:
        self.storage.delete_audio(audio_id)
        session.rollback()
        paper = self.paper_repository.get_paper(session, paper_id)
        audio = self.audio_repository.get_by_id(session, audio_id)
        if paper is not None and paper.status in {
            PaperStatus.PENDING,
            PaperStatus.PROCESSING,
        }:
            paper.status = PaperStatus.FAILED
            paper.error_summary = f"Paper rendering failed ({type(exception).__name__})"
        if audio is not None:
            if audio.status is AudioStatus.PENDING:
                self.audio_service.transition_status(
                    session,
                    audio,
                    AudioStatus.PROCESSING,
                )
            if audio.status is AudioStatus.PROCESSING:
                self.audio_service.transition_status(
                    session,
                    audio,
                    AudioStatus.FAILED,
                    error_summary=f"Paper rendering failed ({type(exception).__name__})",
                )
        session.commit()
        logger.bind(
            request_id=request_id,
            job_id=job_id,
            user_db_id=paper.owner_id if paper is not None else "-",
            resource_type="paper",
            resource_id=paper_id,
        ).error(
            "Paper rendering failed paper_id={} audio_id={} exception_type={}",
            paper_id,
            audio_id,
            type(exception).__name__,
        )
        raise JobFailedError("Paper rendering failed") from exception

    @staticmethod
    def _combined_text(paper: Paper) -> str:
        return "\n\n".join(
            f"{position + 1}. {item.audio.title}\n{item.audio.text}"
            for position, item in enumerate(paper.items)
        )
