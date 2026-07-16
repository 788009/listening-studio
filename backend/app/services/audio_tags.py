from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.services.tag_values import (
    TagTranslationInput,
    normalize_english_tag_value,
    normalize_tag_translations,
)


class AudioTagService:
    def __init__(self, repository: AudioTagRepository | None = None) -> None:
        self.repository = repository or AudioTagRepository()

    def create_tag(
        self,
        session: Session,
        *,
        tag_type: AudioTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> AudioTag:
        if not isinstance(tag_type, AudioTagType):
            raise DomainValidationError(
                "Audio tag type is invalid",
                details={"field": "type"},
            )
        english = normalize_english_tag_value(english_value)
        normalized_translations = normalize_tag_translations(translations)
        existing = self.repository.get_by_normalized_value(
            session,
            tag_type,
            english.normalized_value,
        )
        if existing:
            raise ConflictError("Audio tag already exists")

        try:
            tag = self.repository.create(
                session,
                tag_type=tag_type,
                value=english.value,
                normalized_value=english.normalized_value,
            )
            for translation in normalized_translations:
                self.repository.add_translation(
                    session,
                    tag=tag,
                    language=translation.language,
                    value=translation.value.value,
                    normalized_value=translation.value.normalized_value,
                )
            return tag
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("Audio tag or translation already exists") from exc
