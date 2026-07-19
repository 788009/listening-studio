from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    AudioTitleTakenError,
    ConflictError,
    DomainValidationError,
    ProfileIncompleteError,
)
from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioVisibility,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.db.models.user import User
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.audios import AudioRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.authorization import (
    ResourceDescriptor,
    ResourceKind,
    ResourceStatus,
    ResourceVisibility,
)
from backend.app.services.tag_values import normalize_english_tag_value


_ALLOWED_STATUS_TRANSITIONS: Mapping[AudioStatus, frozenset[AudioStatus]] = {
    AudioStatus.PENDING: frozenset({AudioStatus.PROCESSING}),
    AudioStatus.PROCESSING: frozenset({AudioStatus.READY, AudioStatus.FAILED}),
    AudioStatus.READY: frozenset(),
    AudioStatus.FAILED: frozenset(),
}


@dataclass(frozen=True)
class AudioUtteranceInput:
    voice_id: int
    speaker_display_name: str
    text: str


class AudioService:
    def __init__(
        self,
        storage: AudioStorage,
        repository: AudioRepository | None = None,
        tag_repository: AudioTagRepository | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository or AudioRepository()
        self.tag_repository = tag_repository or AudioTagRepository()

    def create_audio(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        source_type: AudioSourceType,
        text: str | None = None,
        utterances: Iterable[AudioUtteranceInput] = (),
        tags: Iterable[AudioTag] = (),
    ) -> Audio:
        if not author.is_profile_complete or author.user_id is None:
            raise ProfileIncompleteError()
        if not isinstance(source_type, AudioSourceType):
            raise DomainValidationError(
                "Audio source type is invalid",
                details={"field": "sourceType"},
            )
        normalized_title, search_title = self._normalize_title(title)
        if self.repository.get_by_normalized_title(session, search_title):
            raise AudioTitleTakenError(details={"field": "title"})
        normalized_utterances = self._normalize_utterances(utterances)
        if source_type is AudioSourceType.MULTI_TURN and not normalized_utterances:
            raise DomainValidationError(
                "Multi-turn audio requires at least one utterance",
                details={"field": "utterances"},
            )
        normalized_text = self._canonical_text(text, normalized_utterances)
        associated_tags = self._resolve_tags(session, author, tags)

        try:
            audio = self.repository.create(
                session,
                author=author,
                title=normalized_title,
                normalized_title=search_title,
                text=normalized_text,
                source_type=source_type,
                tags=associated_tags,
            )
        except IntegrityError as exc:
            session.rollback()
            if self.repository.get_by_normalized_title(session, search_title):
                raise AudioTitleTakenError(details={"field": "title"}) from exc
            raise
        for position, utterance in enumerate(normalized_utterances):
            self.repository.add_utterance(
                session,
                audio=audio,
                voice_id=utterance.voice_id,
                speaker_display_name=utterance.speaker_display_name,
                text=utterance.text,
                position=position,
            )
        session.flush()
        self.storage.prepare_directory(audio.id)
        return audio

    def record_file_metadata(self, session: Session, audio: Audio) -> Audio:
        if audio.status is not AudioStatus.PROCESSING:
            raise ConflictError("Audio metadata can only be recorded while processing")
        metadata = self.storage.inspect(audio.id)
        audio.audio_format = metadata.audio_format
        audio.duration_seconds = metadata.duration_seconds
        audio.sample_rate = metadata.sample_rate
        audio.channels = metadata.channels
        audio.sample_width_bytes = metadata.sample_width_bytes
        audio.file_size_bytes = metadata.file_size_bytes
        session.flush()
        return audio

    def transition_status(
        self,
        session: Session,
        audio: Audio,
        target_status: AudioStatus,
        *,
        error_summary: str | None = None,
    ) -> Audio:
        if not isinstance(target_status, AudioStatus):
            raise DomainValidationError(
                "Audio status is invalid",
                details={"field": "status"},
            )
        if target_status not in _ALLOWED_STATUS_TRANSITIONS[audio.status]:
            raise ConflictError(
                f"Audio cannot transition from {audio.status.value} "
                f"to {target_status.value}"
            )
        if target_status is AudioStatus.READY:
            if not self.storage.exists(audio.id) or not self._has_metadata(audio):
                raise ConflictError(
                    "Audio file and metadata must exist before it is ready"
                )

        audio.status = target_status
        if target_status is AudioStatus.FAILED:
            audio.error_summary = self._normalize_error_summary(error_summary)
            audio.visibility = AudioVisibility.PRIVATE
        else:
            audio.error_summary = None
        session.flush()
        return audio

    def set_visibility(
        self,
        session: Session,
        audio: Audio,
        visibility: AudioVisibility,
    ) -> Audio:
        if not isinstance(visibility, AudioVisibility):
            raise DomainValidationError(
                "Audio visibility is invalid",
                details={"field": "visibility"},
            )
        if visibility is AudioVisibility.PUBLIC and not self.is_ready(audio):
            raise ConflictError("Only ready audios with files can be public")
        audio.visibility = visibility
        session.flush()
        return audio

    def playback_path(self, audio: Audio) -> Path:
        if not self.is_ready(audio):
            raise ConflictError("Audio is not ready for playback")
        return self.storage.path(audio.id)

    def is_ready(self, audio: Audio) -> bool:
        return (
            audio.status is AudioStatus.READY
            and self.storage.exists(audio.id)
            and self._has_metadata(audio)
        )

    def descriptor(self, audio: Audio) -> ResourceDescriptor:
        return ResourceDescriptor(
            kind=ResourceKind.AUDIO,
            author_id=audio.author_id,
            visibility=ResourceVisibility(audio.visibility.value),
            status=ResourceStatus(audio.status.value),
            file_exists=self.storage.exists(audio.id),
        )

    def update_title(self, session: Session, audio: Audio, title: str) -> Audio:
        value, normalized = self._normalize_title(title)
        existing = self.repository.get_by_normalized_title(session, normalized)
        if existing is not None and existing.id != audio.id:
            raise AudioTitleTakenError(details={"field": "title"})
        audio.title = value
        audio.normalized_title = normalized
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            conflicting = self.repository.get_by_normalized_title(
                session,
                normalized,
            )
            if conflicting is not None and conflicting.id != audio.id:
                raise AudioTitleTakenError(details={"field": "title"}) from exc
            raise
        return audio

    def replace_user_tags(
        self,
        session: Session,
        audio: Audio,
        tags: list[AudioTag],
    ) -> Audio:
        if any(tag.type is AudioTagType.AUTHOR for tag in tags):
            raise DomainValidationError(
                "Author tags are managed by the system",
                details={"field": "tagIds"},
            )
        author_tags = [tag for tag in audio.tags if tag.type is AudioTagType.AUTHOR]
        audio.tags = author_tags + list(dict.fromkeys(tags))
        session.flush()
        return audio

    def replace_topic_category_tags(
        self,
        session: Session,
        audio: Audio,
        tags: list[AudioTag],
    ) -> Audio:
        if any(
            tag.type not in {AudioTagType.TOPIC, AudioTagType.CATEGORY}
            for tag in tags
        ):
            raise DomainValidationError(
                "Batch audio tags must be topics or categories",
                details={"field": "tagIds"},
            )
        preserved = [
            tag
            for tag in audio.tags
            if tag.type in {AudioTagType.AUTHOR, AudioTagType.VOICE}
        ]
        audio.tags = preserved + list(dict.fromkeys(tags))
        session.flush()
        return audio

    def _resolve_tags(
        self,
        session: Session,
        author: User,
        tags: Iterable[AudioTag],
    ) -> list[AudioTag]:
        author_value = normalize_english_tag_value(author.user_id)
        author_tag = self.tag_repository.get_by_normalized_value(
            session,
            AudioTagType.AUTHOR,
            author_value.normalized_value,
        )
        if author_tag is None:
            author_tag = self.tag_repository.create(
                session,
                tag_type=AudioTagType.AUTHOR,
                value=author_value.value,
                normalized_value=author_value.normalized_value,
            )

        result = [author_tag]
        seen_ids = {author_tag.id}
        for tag in tags:
            if not isinstance(tag, AudioTag) or tag.id is None:
                raise DomainValidationError(
                    "Audio tag is invalid",
                    details={"field": "tags"},
                )
            if tag.type is AudioTagType.AUTHOR:
                raise DomainValidationError(
                    "Author tags are managed by the system",
                    details={"field": "tags"},
                )
            if tag.id not in seen_ids:
                result.append(tag)
                seen_ids.add(tag.id)
        return result

    @staticmethod
    def _normalize_title(title: str) -> tuple[str, str]:
        if not isinstance(title, str):
            raise DomainValidationError(
                "Audio title is required",
                details={"field": "title"},
            )
        value = unicodedata.normalize("NFKC", title.strip())
        normalized_value = value.casefold()
        if not value or len(value) > 200 or len(normalized_value) > 200:
            raise DomainValidationError(
                "Audio title must contain between 1 and 200 characters",
                details={"field": "title"},
            )
        return value, normalized_value

    @classmethod
    def _normalize_utterances(
        cls,
        utterances: Iterable[AudioUtteranceInput],
    ) -> list[AudioUtteranceInput]:
        result: list[AudioUtteranceInput] = []
        for utterance in utterances:
            if not isinstance(utterance, AudioUtteranceInput):
                raise DomainValidationError(
                    "Audio utterance is invalid",
                    details={"field": "utterances"},
                )
            if (
                isinstance(utterance.voice_id, bool)
                or not isinstance(utterance.voice_id, int)
                or utterance.voice_id < 1
            ):
                raise DomainValidationError(
                    "Utterance voice ID must be a positive integer",
                    details={"field": "utterances.voiceId"},
                )
            speaker = cls._normalize_text(
                utterance.speaker_display_name,
                "utterances.speakerDisplayName",
                maximum_length=200,
            )
            text = cls._normalize_text(utterance.text, "utterances.text")
            result.append(AudioUtteranceInput(utterance.voice_id, speaker, text))
        return result

    @classmethod
    def _canonical_text(
        cls,
        text: str | None,
        utterances: list[AudioUtteranceInput],
    ) -> str:
        if utterances:
            if len(utterances) == 1:
                return utterances[0].text
            return "\n".join(
                f"{utterance.speaker_display_name}: {utterance.text}"
                for utterance in utterances
            )
        return cls._normalize_text(text, "text")

    @staticmethod
    def _normalize_text(
        value: str | None,
        field: str,
        *,
        maximum_length: int | None = None,
    ) -> str:
        if not isinstance(value, str):
            raise DomainValidationError(
                "Audio text is required",
                details={"field": field},
            )
        normalized = unicodedata.normalize("NFKC", value.strip())
        if not normalized or (
            maximum_length is not None and len(normalized) > maximum_length
        ):
            raise DomainValidationError(
                "Audio text is invalid",
                details={"field": field},
            )
        return normalized

    @staticmethod
    def _has_metadata(audio: Audio) -> bool:
        return bool(
            audio.audio_format == "wav"
            and audio.duration_seconds is not None
            and audio.duration_seconds > 0
            and audio.sample_rate is not None
            and audio.sample_rate > 0
            and audio.channels is not None
            and audio.channels > 0
            and audio.sample_width_bytes is not None
            and audio.sample_width_bytes > 0
            and audio.file_size_bytes is not None
            and audio.file_size_bytes > 0
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
                "Audio error summary is too long",
                details={"field": "errorSummary"},
            )
        return summary
