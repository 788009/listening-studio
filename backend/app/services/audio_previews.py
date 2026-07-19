from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    JobFailedError,
)
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.user import User
from backend.app.integrations.cosyvoice import CosyVoiceIntegration
from backend.app.services.audio_combiner import AudioCombiner
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audio_synthesis import AudioSynthesisService
from backend.app.services.audios import AudioService, AudioUtteranceInput
from backend.app.services.job_storage import AUDIO_PREVIEW_JOB_TYPE, JobStorage
from backend.app.services.jobs import JobService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage


@dataclass(frozen=True)
class AudioPreviewInput:
    voice_id: int
    speaker_display_name: str
    text: str


@dataclass(frozen=True)
class AudioPreviewSubmission:
    job: Job
    content_digest: str


@dataclass(frozen=True)
class PublishedAudioUtterance:
    preview_job_id: int
    voice_id: int
    speaker_display_name: str
    text: str


class AudioPreviewService:
    def __init__(
        self,
        *,
        job_storage: JobStorage,
        voice_storage: VoiceStorage,
        audio_storage: AudioStorage | None = None,
        integration: CosyVoiceIntegration | None = None,
        synthesis_service: AudioSynthesisService | None = None,
        job_service: JobService | None = None,
        audio_service: AudioService | None = None,
        combiner: AudioCombiner | None = None,
    ) -> None:
        self.job_storage = job_storage
        self.voice_storage = voice_storage
        self.audio_storage = audio_storage
        self.inspection_storage = audio_storage or AudioStorage(job_storage.root.parent)
        self.integration = integration
        self.synthesis_service = synthesis_service or AudioSynthesisService(
            audio_storage=self.inspection_storage,
            voice_storage=voice_storage,
        )
        self.job_service = job_service or JobService()
        self.audio_service = audio_service or (
            AudioService(audio_storage) if audio_storage is not None else None
        )
        self.combiner = combiner or AudioCombiner()

    @staticmethod
    def normalize_input(
        voice_id: object,
        speaker_display_name: object,
        text: object,
    ) -> AudioPreviewInput:
        if (
            isinstance(voice_id, bool)
            or not isinstance(voice_id, int)
            or voice_id < 1
            or not isinstance(speaker_display_name, str)
            or not isinstance(text, str)
        ):
            raise DomainValidationError("Audio preview input is invalid")
        speaker = speaker_display_name.strip()
        normalized_text = text.strip()
        if not speaker or len(speaker) > 200:
            raise DomainValidationError(
                "Speaker display name is invalid",
                details={"field": "speakerDisplayName"},
            )
        if not normalized_text:
            raise DomainValidationError(
                "Audio preview text is required",
                details={"field": "text"},
            )
        return AudioPreviewInput(voice_id, speaker, normalized_text)

    @staticmethod
    def content_digest(value: AudioPreviewInput) -> str:
        encoded = json.dumps(
            [value.voice_id, value.speaker_display_name, value.text],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def submit(
        self,
        session: Session,
        *,
        owner: User,
        voice_id: int,
        speaker_display_name: str,
        text: str,
    ) -> AudioPreviewSubmission:
        preview_input = self.normalize_input(voice_id, speaker_display_name, text)
        self.synthesis_service.authorized_voice(session, owner, preview_input.voice_id)
        digest = self.content_digest(preview_input)
        job: Job | None = None
        try:
            job = self.job_service.create_job(
                session,
                owner=owner,
                job_type=AUDIO_PREVIEW_JOB_TYPE,
                input_summary={
                    "voiceId": preview_input.voice_id,
                    "contentDigest": digest,
                },
                retryable=True,
            )
            self.job_storage.write_audio_preview_input(
                job.id,
                {
                    "voiceId": preview_input.voice_id,
                    "speakerDisplayName": preview_input.speaker_display_name,
                    "text": preview_input.text,
                },
            )
            session.commit()
            return AudioPreviewSubmission(job, digest)
        except Exception:
            session.rollback()
            if job is not None:
                self.job_storage.cleanup(job.id)
            raise

    def process(
        self,
        session: Session,
        *,
        job_id: int,
        owner_id: int,
        expected_digest: str,
        checkpoint: Callable[[int], None],
    ) -> None:
        if self.integration is None:
            raise RuntimeError("CosyVoice integration is required for synthesis")
        preview_path = self.job_storage.audio_preview_path(job_id)
        if preview_path.is_file() and not preview_path.is_symlink():
            self.inspection_storage.inspect_file(preview_path)
            return
        owner = session.get(User, owner_id)
        if owner is None:
            raise JobFailedError("Audio preview owner is unavailable")
        try:
            payload = self.job_storage.read_audio_preview_input(job_id)
            preview_input = self.normalize_input(
                payload.get("voiceId"),
                payload.get("speakerDisplayName"),
                payload.get("text"),
            )
        except (OSError, ValueError, TypeError, DomainValidationError) as exc:
            raise JobFailedError("Audio preview input is unavailable") from exc
        if self.content_digest(preview_input) != expected_digest:
            raise JobFailedError("Audio preview input does not match its task")
        checkpoint(15)
        voice = self.synthesis_service.authorized_voice(
            session,
            owner,
            preview_input.voice_id,
        )
        checkpoint(25)
        temporary = self.job_storage.audio_preview_temporary_path(job_id)
        temporary.unlink(missing_ok=True)
        self.integration.synthesize(
            self.voice_storage.path(voice.id, VoiceAsset.MODEL),
            preview_input.text,
            temporary,
        )
        checkpoint(85)
        self.inspection_storage.inspect_file(temporary)
        self.job_storage.finalize_audio_preview(job_id)
        self.job_storage.audio_preview_input_path(job_id).unlink(missing_ok=True)
        checkpoint(95)

    def get_owned_preview(self, session: Session, owner: User, job_id: int) -> Job:
        job = self.job_service.get_owned_job(session, owner, job_id)
        if job.type != AUDIO_PREVIEW_JOB_TYPE:
            raise ConflictError("Job is not an audio preview")
        return job

    def delete(self, session: Session, *, owner: User, job_id: int) -> None:
        job = self.get_owned_preview(session, owner, job_id)
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            self.job_service.request_cancel(session, owner, job_id)
            session.commit()
            if job.status is JobStatus.RUNNING:
                return
        self.job_storage.cleanup(job_id)

    def publish(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        utterances: list[PublishedAudioUtterance],
        tag_ids: list[int],
        visibility: AudioVisibility,
        silence_milliseconds: int,
    ) -> Audio:
        if self.audio_storage is None or self.audio_service is None:
            raise RuntimeError("Audio storage is required for publishing")
        if not utterances:
            raise DomainValidationError(
                "At least one audio preview is required",
                details={"field": "utterances"},
            )
        self.synthesis_service.validate_visibility(visibility)
        self.synthesis_service.validate_silence(silence_milliseconds)
        normalized: list[tuple[PublishedAudioUtterance, AudioPreviewInput, Job]] = []
        for item in utterances:
            value = self.normalize_input(
                item.voice_id,
                item.speaker_display_name,
                item.text,
            )
            job = self.get_owned_preview(session, author, item.preview_job_id)
            digest = self.content_digest(value)
            if (
                job.status is not JobStatus.SUCCEEDED
                or job.input_summary.get("voiceId") != value.voice_id
                or job.input_summary.get("contentDigest") != digest
                or not self.job_storage.audio_preview_path(job.id).is_file()
            ):
                raise ConflictError("Audio preview is missing or out of date")
            self.inspection_storage.inspect_file(
                self.job_storage.audio_preview_path(job.id)
            )
            self.synthesis_service.authorized_voice(session, author, value.voice_id)
            normalized.append((item, value, job))

        names = {
            unicodedata.normalize("NFKC", value.speaker_display_name).casefold()
            for _, value, _ in normalized
        }
        source_type = (
            AudioSourceType.SINGLE_SPEAKER
            if len(names) == 1
            else AudioSourceType.MULTI_TURN
        )
        utterance_inputs = [
            AudioUtteranceInput(value.voice_id, value.speaker_display_name, value.text)
            for _, value, _ in normalized
        ]
        tags = self.synthesis_service.resolve_tags(session, tag_ids)
        tags.extend(self.synthesis_service.voice_tags(session, utterance_inputs))
        audio: Audio | None = None
        try:
            audio = self.audio_service.create_audio(
                session,
                author=author,
                title=title,
                source_type=source_type,
                utterances=utterance_inputs,
                tags=tags,
            )
            self.audio_service.transition_status(session, audio, AudioStatus.PROCESSING)
            self.combiner.combine_wav(
                [
                    self.job_storage.audio_preview_path(job.id)
                    for _, _, job in normalized
                ],
                self.audio_storage.publishing_path(audio.id),
                silence_milliseconds=silence_milliseconds if len(normalized) > 1 else 0,
            )
            self.audio_storage.inspect_file(
                self.audio_storage.publishing_path(audio.id)
            )
            self.audio_storage.finalize_publishing(audio.id)
            self.audio_service.record_file_metadata(session, audio)
            self.audio_service.transition_status(session, audio, AudioStatus.READY)
            self.audio_service.set_visibility(session, audio, visibility)
            session.commit()
        except Exception:
            session.rollback()
            if audio is not None:
                self.audio_storage.delete_audio(audio.id)
            raise
        for _, _, job in normalized:
            try:
                self.job_storage.cleanup(job.id)
            except OSError:
                logger.bind(
                    job_id=job.id, resource_type="job", resource_id=job.id
                ).warning("Published audio preview cleanup failed job_id={}", job.id)
        return audio
