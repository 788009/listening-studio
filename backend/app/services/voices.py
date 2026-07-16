from __future__ import annotations

import unicodedata
from collections.abc import Mapping

from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    ProfileIncompleteError,
)
from backend.app.db.models.user import User
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)
from backend.app.db.models.voice_tag import VoiceTagType
from backend.app.db.models.voice_tag import VoiceTag
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.authorization import (
    ResourceDescriptor,
    ResourceKind,
    ResourceStatus,
    ResourceVisibility,
)
from backend.app.services.tag_values import normalize_english_tag_value
from backend.app.services.voice_storage import VoiceStorage


_ALLOWED_STATUS_TRANSITIONS: Mapping[VoiceStatus, frozenset[VoiceStatus]] = {
    VoiceStatus.PENDING: frozenset({VoiceStatus.PROCESSING}),
    VoiceStatus.PROCESSING: frozenset({VoiceStatus.READY, VoiceStatus.FAILED}),
    VoiceStatus.READY: frozenset(),
    VoiceStatus.FAILED: frozenset(),
}


class VoiceService:
    def __init__(
        self,
        storage: VoiceStorage,
        repository: VoiceRepository | None = None,
        tag_repository: VoiceTagRepository | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository or VoiceRepository()
        self.tag_repository = tag_repository or VoiceTagRepository()

    def create_voice(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        sample_source: VoiceSampleSource = VoiceSampleSource.ORIGINAL,
        sample_audio_id: int | None = None,
    ) -> Voice:
        if not author.is_profile_complete or author.user_id is None:
            raise ProfileIncompleteError()
        normalized_title, search_title = self._normalize_title(title)
        self._validate_sample_source(sample_source, sample_audio_id)

        author_value = normalize_english_tag_value(author.user_id)
        author_tag = self.tag_repository.get_by_normalized_value(
            session,
            VoiceTagType.AUTHOR,
            author_value.normalized_value,
        )
        if author_tag is None:
            author_tag = self.tag_repository.create(
                session,
                tag_type=VoiceTagType.AUTHOR,
                value=author_value.value,
                normalized_value=author_value.normalized_value,
            )

        voice = self.repository.create(
            session,
            author=author,
            title=normalized_title,
            normalized_title=search_title,
            sample_source=sample_source,
            sample_audio_id=sample_audio_id,
            author_tag=author_tag,
        )
        self.storage.prepare_directory(voice.id)
        return voice

    def transition_status(
        self,
        session: Session,
        voice: Voice,
        target_status: VoiceStatus,
        *,
        error_summary: str | None = None,
    ) -> Voice:
        if not isinstance(target_status, VoiceStatus):
            raise DomainValidationError(
                "Voice status is invalid",
                details={"field": "status"},
            )
        if target_status not in _ALLOWED_STATUS_TRANSITIONS[voice.status]:
            raise ConflictError(
                f"Voice cannot transition from {voice.status.value} "
                f"to {target_status.value}"
            )
        if target_status is VoiceStatus.READY and not self.storage.exists(voice.id):
            raise ConflictError("Voice model file must exist before it is ready")

        voice.status = target_status
        if target_status is VoiceStatus.FAILED:
            voice.error_summary = self._normalize_error_summary(error_summary)
            voice.visibility = VoiceVisibility.PRIVATE
        else:
            voice.error_summary = None
        session.flush()
        return voice

    def set_visibility(
        self,
        session: Session,
        voice: Voice,
        visibility: VoiceVisibility,
    ) -> Voice:
        if not isinstance(visibility, VoiceVisibility):
            raise DomainValidationError(
                "Voice visibility is invalid",
                details={"field": "visibility"},
            )
        if visibility is VoiceVisibility.PUBLIC and not self.is_ready(voice):
            raise ConflictError("Only ready voices with model files can be public")
        voice.visibility = visibility
        session.flush()
        return voice

    def is_ready(self, voice: Voice) -> bool:
        return voice.status is VoiceStatus.READY and self.storage.exists(voice.id)

    def descriptor(self, voice: Voice) -> ResourceDescriptor:
        return ResourceDescriptor(
            kind=ResourceKind.VOICE,
            author_id=voice.author_id,
            visibility=ResourceVisibility(voice.visibility.value),
            status=ResourceStatus(voice.status.value),
            file_exists=self.storage.exists(voice.id),
        )

    def update_title(self, session: Session, voice: Voice, title: str) -> Voice:
        normalized_title, search_title = self._normalize_title(title)
        voice.title = normalized_title
        voice.normalized_title = search_title
        session.flush()
        return voice

    def replace_gender_tags(
        self,
        session: Session,
        voice: Voice,
        gender_tags: list[VoiceTag],
    ) -> Voice:
        if any(tag.type is not VoiceTagType.GENDER for tag in gender_tags):
            raise DomainValidationError(
                "Voice tags must have gender type",
                details={"field": "genderTagIds"},
            )
        author_tags = [tag for tag in voice.tags if tag.type is VoiceTagType.AUTHOR]
        voice.tags = author_tags + list(dict.fromkeys(gender_tags))
        session.flush()
        return voice

    @staticmethod
    def _normalize_title(title: str) -> tuple[str, str]:
        if not isinstance(title, str):
            raise DomainValidationError(
                "Voice title is required",
                details={"field": "title"},
            )
        value = unicodedata.normalize("NFKC", title.strip())
        normalized_value = value.casefold()
        if not value or len(value) > 200 or len(normalized_value) > 200:
            raise DomainValidationError(
                "Voice title must contain between 1 and 200 characters",
                details={"field": "title"},
            )
        return value, normalized_value

    def set_sample_source(
        self,
        session: Session,
        voice: Voice,
        sample_source: VoiceSampleSource,
        sample_audio_id: int | None,
    ) -> Voice:
        self._validate_sample_source(sample_source, sample_audio_id)
        voice.sample_source = sample_source
        voice.sample_audio_id = sample_audio_id
        session.flush()
        return voice

    @staticmethod
    def _validate_sample_source(
        sample_source: VoiceSampleSource,
        sample_audio_id: int | None,
    ) -> None:
        if not isinstance(sample_source, VoiceSampleSource):
            raise DomainValidationError(
                "Voice sample source is invalid",
                details={"field": "sampleSource"},
            )
        has_audio_id = (
            isinstance(sample_audio_id, int)
            and not isinstance(sample_audio_id, bool)
            and sample_audio_id > 0
        )
        if (
            sample_source is VoiceSampleSource.ORIGINAL
            and sample_audio_id is not None
        ):
            raise DomainValidationError(
                "Original samples cannot specify an audio ID",
                details={"field": "sampleAudioId"},
            )
        if sample_source is VoiceSampleSource.PUBLIC_AUDIO and not has_audio_id:
            raise DomainValidationError(
                "Public audio samples require a positive audio ID",
                details={"field": "sampleAudioId"},
            )

    @staticmethod
    def _normalize_error_summary(error_summary: str | None) -> str | None:
        if error_summary is None:
            return None
        summary = error_summary.strip()
        if not summary:
            return None
        if len(summary) > 1000:
            raise DomainValidationError(
                "Voice error summary is too long",
                details={"field": "errorSummary"},
            )
        return summary
