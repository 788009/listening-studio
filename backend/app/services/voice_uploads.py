from __future__ import annotations

import io
import shutil
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    DomainValidationError,
    JobFailedError,
    NotFoundError,
)
from backend.app.db.models.job import Job
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.integrations.cosyvoice import CosyVoiceIntegration
from backend.app.integrations.audio_conversion import (
    AudioConversionError,
    FfmpegAudioTranscoder,
)
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.job_storage import JobStorage
from backend.app.services.jobs import JobService
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


DEFAULT_MIN_REFERENCE_SECONDS = 1.0
DEFAULT_MAX_REFERENCE_SECONDS = 30.0
SUPPORTED_REFERENCE_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm"}
)
VOICE_UPLOAD_JOB_TYPE = "voice_upload"


@dataclass(frozen=True)
class ValidatedReferenceAudio:
    wav_data: bytes
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int


@dataclass(frozen=True)
class VoiceUploadSubmission:
    voice: Voice
    job: Job


class ReferenceAudioTranscoder(Protocol):
    def convert_to_wav(
        self,
        content: bytes,
        *,
        extension: str,
        max_duration_seconds: float,
    ) -> bytes:
        pass


class ReferenceAudioValidator:
    def __init__(
        self,
        *,
        max_upload_bytes: int,
        min_duration_seconds: float = DEFAULT_MIN_REFERENCE_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_REFERENCE_SECONDS,
        transcoder: ReferenceAudioTranscoder | None = None,
    ) -> None:
        if max_upload_bytes < 1:
            raise ValueError("Maximum upload size must be positive")
        if min_duration_seconds <= 0 or max_duration_seconds <= min_duration_seconds:
            raise ValueError("Reference audio duration bounds are invalid")
        self.max_upload_bytes = max_upload_bytes
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.transcoder = transcoder or FfmpegAudioTranscoder()

    def validate(self, filename: str, content: bytes) -> ValidatedReferenceAudio:
        extension = self._validate_filename(filename)
        if not isinstance(content, bytes):
            raise DomainValidationError(
                "Reference audio content is invalid",
                details={"field": "file"},
            )
        if not content:
            raise DomainValidationError(
                "Reference audio cannot be empty",
                details={"field": "file"},
            )
        if len(content) > self.max_upload_bytes:
            raise DomainValidationError(
                "Reference audio exceeds the upload size limit",
                details={
                    "field": "file",
                    "maxBytes": self.max_upload_bytes,
                },
            )
        wav_content = content
        if extension != ".wav":
            try:
                wav_content = self.transcoder.convert_to_wav(
                    content,
                    extension=extension,
                    max_duration_seconds=self.max_duration_seconds,
                )
            except AudioConversionError as exc:
                raise DomainValidationError(
                    "Reference audio could not be decoded",
                    details={"field": "file"},
                ) from exc
        try:
            with wave.open(io.BytesIO(wav_content), "rb") as audio_file:
                if audio_file.getcomptype() != "NONE":
                    raise DomainValidationError(
                        "Reference WAV compression is not supported",
                        details={"field": "file"},
                    )
                channels = audio_file.getnchannels()
                sample_width = audio_file.getsampwidth()
                sample_rate = audio_file.getframerate()
                frame_count = audio_file.getnframes()
                frames = audio_file.readframes(frame_count)
        except DomainValidationError:
            raise
        except (EOFError, wave.Error) as exc:
            raise DomainValidationError(
                "Reference audio is not a valid WAV file",
                details={"field": "file"},
            ) from exc

        if channels not in {1, 2}:
            raise DomainValidationError(
                "Reference audio must have one or two channels",
                details={"field": "file"},
            )
        if sample_width not in {1, 2, 3, 4} or sample_rate <= 0:
            raise DomainValidationError(
                "Reference audio sample format is invalid",
                details={"field": "file"},
            )
        expected_frame_bytes = frame_count * channels * sample_width
        if frame_count <= 0 or len(frames) != expected_frame_bytes:
            raise DomainValidationError(
                "Reference audio contains incomplete or empty samples",
                details={"field": "file"},
            )
        duration_seconds = frame_count / sample_rate
        if not (
            self.min_duration_seconds
            <= duration_seconds
            <= self.max_duration_seconds
        ):
            raise DomainValidationError(
                "Reference audio duration is outside the allowed range",
                details={
                    "field": "file",
                    "minSeconds": self.min_duration_seconds,
                    "maxSeconds": self.max_duration_seconds,
                },
            )

        normalized = io.BytesIO()
        with wave.open(normalized, "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            output.writeframes(frames)
        return ValidatedReferenceAudio(
            wav_data=normalized.getvalue(),
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=channels,
            sample_width_bytes=sample_width,
        )

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise DomainValidationError(
                "Reference audio filename is required",
                details={"field": "filename"},
            )
        extension = Path(filename).suffix.casefold()
        if extension not in SUPPORTED_REFERENCE_EXTENSIONS:
            raise DomainValidationError(
                "Reference audio format is not supported",
                details={"field": "filename"},
            )
        return extension


class VoiceUploadService:
    def __init__(
        self,
        *,
        storage: VoiceStorage,
        max_upload_bytes: int,
        integration: CosyVoiceIntegration | None = None,
        job_storage: JobStorage | None = None,
        job_service: JobService | None = None,
        voice_service: VoiceService | None = None,
        voice_repository: VoiceRepository | None = None,
        tag_repository: VoiceTagRepository | None = None,
        min_duration_seconds: float = DEFAULT_MIN_REFERENCE_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_REFERENCE_SECONDS,
        audio_transcoder: ReferenceAudioTranscoder | None = None,
    ) -> None:
        self.integration = integration
        self.storage = storage
        self.job_storage = job_storage
        self.job_service = job_service or JobService()
        self.voice_service = voice_service or VoiceService(storage)
        self.voice_repository = voice_repository or VoiceRepository()
        self.tag_repository = tag_repository or VoiceTagRepository()
        self.validator = ReferenceAudioValidator(
            max_upload_bytes=max_upload_bytes,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            transcoder=audio_transcoder,
        )

    def prepare_async_upload(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        filename: str,
        content: bytes,
        gender_tag_id: int | None = None,
        target_visibility: VoiceVisibility = VoiceVisibility.PRIVATE,
    ) -> VoiceUploadSubmission:
        if self.job_storage is None:
            raise RuntimeError("Job storage is required for asynchronous uploads")
        reference = self.validator.validate(filename, content)
        self._validate_target_visibility(target_visibility)
        gender_tag = self._get_gender_tag(session, gender_tag_id)
        voice: Voice | None = None
        job: Job | None = None
        try:
            voice = self.voice_service.create_voice(
                session,
                author=author,
                title=title,
            )
            if gender_tag is not None:
                voice.tags.append(gender_tag)
            job = self.job_service.create_job(
                session,
                owner=author,
                job_type=VOICE_UPLOAD_JOB_TYPE,
                input_summary={
                    "voiceId": voice.id,
                    "targetVisibility": target_visibility.value,
                    "referenceDurationSeconds": round(
                        reference.duration_seconds,
                        3,
                    ),
                    "sampleRate": reference.sample_rate,
                    "channels": reference.channels,
                },
                retryable=True,
            )
            self.job_storage.write_reference(job.id, reference.wav_data)
            session.commit()
            return VoiceUploadSubmission(voice=voice, job=job)
        except Exception:
            session.rollback()
            if job is not None:
                self.job_storage.cleanup(job.id)
            if voice is not None:
                self.storage.delete(voice.id)
            raise

    def process_async_upload(
        self,
        session: Session,
        *,
        voice_id: int,
        job_id: int,
        target_visibility: VoiceVisibility,
        request_id: str,
        checkpoint: Callable[[int], None],
    ) -> Voice:
        if self.job_storage is None:
            raise RuntimeError("Job storage is required for asynchronous uploads")
        if self.integration is None:
            raise RuntimeError("CosyVoice integration is required for generation")
        voice = self.voice_repository.get_by_id(session, voice_id)
        if voice is None:
            raise JobFailedError("Voice record is unavailable")
        if voice.status is VoiceStatus.READY and self.storage.exists(voice.id):
            self.job_storage.cleanup(job_id)
            return voice
        if voice.status is VoiceStatus.PENDING:
            self.voice_service.transition_status(
                session,
                voice,
                VoiceStatus.PROCESSING,
            )
            session.commit()
        elif voice.status is not VoiceStatus.PROCESSING:
            raise JobFailedError("Voice cannot be generated from its current state")

        reference_temporary: Path | None = None
        model_temporary: Path | None = None
        try:
            checkpoint(10)
            staged_reference = self.job_storage.reference_path(job_id)
            if not staged_reference.is_file() or staged_reference.is_symlink():
                raise JobFailedError("Staged reference audio is unavailable")
            reference_temporary = self.storage.create_temporary_file(
                voice.id,
                VoiceAsset.REFERENCE,
            )
            shutil.copyfile(staged_reference, reference_temporary)
            model_temporary = self.storage.create_temporary_file(
                voice.id,
                VoiceAsset.MODEL,
            )
            checkpoint(20)
            self.integration.extract_voice(reference_temporary, model_temporary)
            checkpoint(80)
            self.storage.atomic_replace(
                voice.id,
                VoiceAsset.REFERENCE,
                reference_temporary,
            )
            reference_temporary = None
            self.storage.atomic_replace(
                voice.id,
                VoiceAsset.MODEL,
                model_temporary,
            )
            model_temporary = None
            checkpoint(90)
            self.voice_service.transition_status(session, voice, VoiceStatus.READY)
            self.voice_service.set_visibility(session, voice, target_visibility)
            session.commit()
            logger.bind(
                request_id=request_id,
                job_id=job_id,
                user_db_id=voice.author_id,
                resource_type="voice",
                resource_id=voice.id,
            ).info(
                "Voice upload completed voice_id={} job_id={}",
                voice.id,
                job_id,
            )
            return voice
        except Exception as exc:
            self._handle_failure(
                session,
                voice.id,
                job_id=job_id,
                request_id=request_id,
                exception=exc,
                temporary_paths=(reference_temporary, model_temporary),
            )
        finally:
            self.job_storage.cleanup(job_id)

    def create_from_upload(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        filename: str,
        content: bytes,
        gender_tag_id: int | None = None,
        target_visibility: VoiceVisibility = VoiceVisibility.PRIVATE,
        request_id: str,
    ) -> Voice:
        if self.integration is None:
            raise RuntimeError("CosyVoice integration is required for generation")
        reference = self.validator.validate(filename, content)
        self._validate_target_visibility(target_visibility)
        gender_tag = self._get_gender_tag(session, gender_tag_id)

        voice = self.voice_service.create_voice(
            session,
            author=author,
            title=title,
        )
        if gender_tag is not None:
            voice.tags.append(gender_tag)
        self.voice_service.transition_status(
            session,
            voice,
            VoiceStatus.PROCESSING,
        )
        session.commit()

        reference_temporary: Path | None = None
        model_temporary: Path | None = None
        try:
            reference_temporary = self.storage.create_temporary_file(
                voice.id,
                VoiceAsset.REFERENCE,
            )
            reference_temporary.write_bytes(reference.wav_data)
            model_temporary = self.storage.create_temporary_file(
                voice.id,
                VoiceAsset.MODEL,
            )
            self.integration.extract_voice(reference_temporary, model_temporary)
            self.storage.atomic_replace(
                voice.id,
                VoiceAsset.REFERENCE,
                reference_temporary,
            )
            reference_temporary = None
            self.storage.atomic_replace(
                voice.id,
                VoiceAsset.MODEL,
                model_temporary,
            )
            model_temporary = None
            self.voice_service.transition_status(session, voice, VoiceStatus.READY)
            self.voice_service.set_visibility(session, voice, target_visibility)
            session.commit()
        except Exception as exc:
            self._handle_failure(
                session,
                voice.id,
                job_id=None,
                request_id=request_id,
                exception=exc,
                temporary_paths=(reference_temporary, model_temporary),
            )

        logger.bind(request_id=request_id).info(
            "Voice upload completed voice_id={}", voice.id
        )
        return voice

    def _handle_failure(
        self,
        session: Session,
        voice_id: int,
        *,
        job_id: int | None,
        request_id: str,
        exception: Exception,
        temporary_paths: tuple[Path | None, Path | None],
    ) -> None:
        for temporary_path in temporary_paths:
            if temporary_path is not None:
                self.storage.discard_temporary_file(temporary_path)
        self.storage.delete(voice_id)
        session.rollback()
        voice = self.voice_repository.get_by_id(session, voice_id)
        if voice is None:
            raise JobFailedError("Voice generation failed") from exception
        self.voice_service.transition_status(
            session,
            voice,
            VoiceStatus.FAILED,
            error_summary=self._error_summary(exception),
        )
        session.commit()
        logger.bind(
            request_id=request_id,
            job_id=job_id or "-",
            user_db_id=voice.author_id,
            resource_type="voice",
            resource_id=voice_id,
        ).error(
            "Voice upload failed voice_id={} exception_type={}",
            voice_id,
            type(exception).__name__,
        )
        raise JobFailedError(
            "Voice generation failed",
            details={"voiceId": voice_id},
        ) from exception

    def _get_gender_tag(
        self,
        session: Session,
        tag_id: int | None,
    ) -> VoiceTag | None:
        if tag_id is None:
            return None
        if isinstance(tag_id, bool) or not isinstance(tag_id, int) or tag_id < 1:
            raise DomainValidationError(
                "Gender tag ID must be a positive integer",
                details={"field": "genderTagId"},
            )
        tag = self.tag_repository.get_by_id(session, tag_id)
        if tag is None:
            raise NotFoundError("Voice gender tag not found")
        if tag.type is not VoiceTagType.GENDER:
            raise DomainValidationError(
                "Voice tag must have gender type",
                details={"field": "genderTagId"},
            )
        return tag

    @staticmethod
    def _validate_target_visibility(visibility: VoiceVisibility) -> None:
        if not isinstance(visibility, VoiceVisibility):
            raise DomainValidationError(
                "Voice visibility is invalid",
                details={"field": "visibility"},
            )

    @staticmethod
    def _error_summary(exception: Exception) -> str:
        return f"Voice generation failed ({type(exception).__name__})"
