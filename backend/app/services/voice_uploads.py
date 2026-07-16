from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    DomainValidationError,
    JobFailedError,
    NotFoundError,
)
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.integrations.cosyvoice import CosyVoiceIntegration
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


DEFAULT_MIN_REFERENCE_SECONDS = 1.0
DEFAULT_MAX_REFERENCE_SECONDS = 30.0
SUPPORTED_REFERENCE_EXTENSION = ".wav"


@dataclass(frozen=True)
class ValidatedReferenceAudio:
    wav_data: bytes
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int


class ReferenceAudioValidator:
    def __init__(
        self,
        *,
        max_upload_bytes: int,
        min_duration_seconds: float = DEFAULT_MIN_REFERENCE_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_REFERENCE_SECONDS,
    ) -> None:
        if max_upload_bytes < 1:
            raise ValueError("Maximum upload size must be positive")
        if min_duration_seconds <= 0 or max_duration_seconds <= min_duration_seconds:
            raise ValueError("Reference audio duration bounds are invalid")
        self.max_upload_bytes = max_upload_bytes
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds

    def validate(self, filename: str, content: bytes) -> ValidatedReferenceAudio:
        self._validate_filename(filename)
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
        try:
            with wave.open(io.BytesIO(content), "rb") as audio_file:
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
    def _validate_filename(filename: str) -> None:
        if not isinstance(filename, str) or not filename.strip():
            raise DomainValidationError(
                "Reference audio filename is required",
                details={"field": "filename"},
            )
        if Path(filename).suffix.casefold() != SUPPORTED_REFERENCE_EXTENSION:
            raise DomainValidationError(
                "Reference audio must use the .wav extension",
                details={"field": "filename"},
            )


class VoiceUploadService:
    def __init__(
        self,
        *,
        integration: CosyVoiceIntegration,
        storage: VoiceStorage,
        max_upload_bytes: int,
        voice_service: VoiceService | None = None,
        voice_repository: VoiceRepository | None = None,
        tag_repository: VoiceTagRepository | None = None,
        min_duration_seconds: float = DEFAULT_MIN_REFERENCE_SECONDS,
        max_duration_seconds: float = DEFAULT_MAX_REFERENCE_SECONDS,
    ) -> None:
        self.integration = integration
        self.storage = storage
        self.voice_service = voice_service or VoiceService(storage)
        self.voice_repository = voice_repository or VoiceRepository()
        self.tag_repository = tag_repository or VoiceTagRepository()
        self.validator = ReferenceAudioValidator(
            max_upload_bytes=max_upload_bytes,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )

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
        logger.bind(request_id=request_id).error(
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
