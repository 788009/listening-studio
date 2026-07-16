from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import (
    DomainValidationError,
    JobFailedError,
    NotFoundError,
)
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.job import Job
from backend.app.db.models.user import User
from backend.app.integrations.cosyvoice import CosyVoiceIntegration
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.audios import AudioRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService, AudioUtteranceInput
from backend.app.services.authorization import AuthorizationService
from backend.app.services.jobs import JobService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


AUDIO_SYNTHESIS_JOB_TYPE = "audio_synthesis"


@dataclass(frozen=True)
class AudioSynthesisSubmission:
    audio: Audio
    job: Job


class AudioSynthesisService:
    def __init__(
        self,
        *,
        audio_storage: AudioStorage,
        voice_storage: VoiceStorage,
        integration: CosyVoiceIntegration | None = None,
        audio_service: AudioService | None = None,
        voice_service: VoiceService | None = None,
        audio_repository: AudioRepository | None = None,
        voice_repository: VoiceRepository | None = None,
        tag_repository: AudioTagRepository | None = None,
        job_service: JobService | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self.audio_storage = audio_storage
        self.voice_storage = voice_storage
        self.integration = integration
        self.audio_service = audio_service or AudioService(audio_storage)
        self.voice_service = voice_service or VoiceService(voice_storage)
        self.audio_repository = audio_repository or AudioRepository()
        self.voice_repository = voice_repository or VoiceRepository()
        self.tag_repository = tag_repository or AudioTagRepository()
        self.job_service = job_service or JobService()
        self.authorization = authorization or AuthorizationService()

    def prepare_single_speaker(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        text: str,
        voice_id: int,
        tag_ids: list[int],
        target_visibility: AudioVisibility,
    ) -> AudioSynthesisSubmission:
        self._validate_visibility(target_visibility)
        voice = self.voice_repository.get_by_id(session, voice_id)
        if voice is None:
            raise NotFoundError("Voice not found")
        self.authorization.require_use_for_synthesis(
            Principal(author),
            self.voice_service.descriptor(voice),
        )
        tags = self._tags(session, tag_ids)
        audio: Audio | None = None
        try:
            audio = self.audio_service.create_audio(
                session,
                author=author,
                title=title,
                source_type=AudioSourceType.SINGLE_SPEAKER,
                utterances=[
                    AudioUtteranceInput(
                        voice_id=voice.id,
                        speaker_display_name=voice.title,
                        text=text,
                    )
                ],
                tags=tags,
            )
            job = self.job_service.create_job(
                session,
                owner=author,
                job_type=AUDIO_SYNTHESIS_JOB_TYPE,
                input_summary={
                    "audioId": audio.id,
                    "targetVisibility": target_visibility.value,
                },
                retryable=True,
            )
            session.commit()
            return AudioSynthesisSubmission(audio=audio, job=job)
        except Exception:
            session.rollback()
            if audio is not None:
                self.audio_storage.delete_audio(audio.id)
            raise

    def process_single_speaker(
        self,
        session: Session,
        *,
        audio_id: int,
        job_id: int,
        target_visibility: AudioVisibility,
        request_id: str,
        checkpoint: Callable[[], None],
    ) -> Audio:
        if self.integration is None:
            raise RuntimeError("CosyVoice integration is required for synthesis")
        audio = self.audio_repository.get_by_id(session, audio_id)
        if audio is None:
            self.audio_storage.cleanup_job(job_id)
            raise JobFailedError("Audio record is unavailable")

        try:
            if audio.status is AudioStatus.READY and self.audio_service.is_ready(audio):
                return audio
            if audio.status is AudioStatus.PENDING:
                self.audio_service.transition_status(
                    session,
                    audio,
                    AudioStatus.PROCESSING,
                )
                session.commit()
            elif audio.status is not AudioStatus.PROCESSING:
                raise JobFailedError(
                    "Audio cannot be generated from its current state"
                )

            if self.audio_storage.exists(audio.id):
                return self._complete_existing(
                    session,
                    audio,
                    target_visibility=target_visibility,
                )
            if (
                audio.source_type is not AudioSourceType.SINGLE_SPEAKER
                or len(audio.utterances) != 1
            ):
                raise JobFailedError("Single-speaker audio task data is invalid")
            utterance = audio.utterances[0]
            voice_path = self.voice_storage.path(
                utterance.voice_id,
                VoiceAsset.MODEL,
            )

            checkpoint()
            output = self.audio_storage.temporary_audio_path(job_id)
            self.integration.synthesize(voice_path, utterance.text, output)
            checkpoint()
            self.audio_storage.inspect_temporary(job_id)
            self.audio_storage.atomic_replace(audio.id, job_id)
            self.audio_service.record_file_metadata(session, audio)
            self.audio_service.transition_status(session, audio, AudioStatus.READY)
            self.audio_service.set_visibility(session, audio, target_visibility)
            session.commit()
            logger.bind(request_id=request_id).info(
                "Audio synthesis completed audio_id={} job_id={}",
                audio.id,
                job_id,
            )
            return audio
        except Exception as exc:
            self._handle_failure(
                session,
                audio.id,
                request_id=request_id,
                exception=exc,
            )
        finally:
            self.audio_storage.cleanup_job(job_id)

    def _complete_existing(
        self,
        session: Session,
        audio: Audio,
        *,
        target_visibility: AudioVisibility,
    ) -> Audio:
        self.audio_service.record_file_metadata(session, audio)
        self.audio_service.transition_status(session, audio, AudioStatus.READY)
        self.audio_service.set_visibility(session, audio, target_visibility)
        session.commit()
        return audio

    def _handle_failure(
        self,
        session: Session,
        audio_id: int,
        *,
        request_id: str,
        exception: Exception,
    ) -> None:
        self.audio_storage.delete_audio(audio_id)
        session.rollback()
        audio = self.audio_repository.get_by_id(session, audio_id)
        if audio is None:
            raise JobFailedError("Audio synthesis failed") from exception
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
                error_summary=f"Audio synthesis failed ({type(exception).__name__})",
            )
            session.commit()
        logger.bind(request_id=request_id).error(
            "Audio synthesis failed audio_id={} exception_type={}",
            audio_id,
            type(exception).__name__,
        )
        raise JobFailedError(
            "Audio synthesis failed",
            details={"audioId": audio_id},
        ) from exception

    def _tags(self, session: Session, tag_ids: list[int]) -> list[AudioTag]:
        tags: list[AudioTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = self.tag_repository.get_by_id(session, tag_id)
            if tag is None or tag.type is AudioTagType.AUTHOR:
                raise NotFoundError("Audio tag not found")
            tags.append(tag)
        return tags

    @staticmethod
    def _validate_visibility(visibility: AudioVisibility) -> None:
        if not isinstance(visibility, AudioVisibility):
            raise DomainValidationError(
                "Audio visibility is invalid",
                details={"field": "visibility"},
            )
