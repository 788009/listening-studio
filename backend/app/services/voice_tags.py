from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.schemas import LanguageCode
from backend.app.core.exceptions import ConflictError, DomainValidationError
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.services.tag_values import (
    NormalizedTagValue,
    normalize_english_tag_value,
    normalize_translated_tag_value,
)


_LANGUAGE_CODE_ADAPTER = TypeAdapter(LanguageCode)


@dataclass(frozen=True)
class TagTranslationInput:
    language: str
    value: str


class VoiceTagService:
    def __init__(self, repository: VoiceTagRepository | None = None) -> None:
        self.repository = repository or VoiceTagRepository()

    def create_tag(
        self,
        session: Session,
        *,
        tag_type: VoiceTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> VoiceTag:
        english = normalize_english_tag_value(english_value)
        normalized_translations = self._normalize_translations(translations)
        existing = self.repository.get_by_normalized_value(
            session,
            tag_type,
            english.normalized_value,
        )
        if existing:
            raise ConflictError("Voice tag already exists")

        try:
            tag = self.repository.create(
                session,
                tag_type=tag_type,
                value=english.value,
                normalized_value=english.normalized_value,
            )
            for language, translation in normalized_translations:
                self.repository.add_translation(
                    session,
                    tag=tag,
                    language=language,
                    value=translation.value,
                    normalized_value=translation.normalized_value,
                )
            return tag
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("Voice tag or translation already exists") from exc

    @staticmethod
    def _normalize_translations(
        translations: Iterable[TagTranslationInput],
    ) -> list[tuple[str, NormalizedTagValue]]:
        result: list[tuple[str, NormalizedTagValue]] = []
        languages: set[str] = set()
        for translation in translations:
            try:
                language = _LANGUAGE_CODE_ADAPTER.validate_python(
                    translation.language
                )
            except ValidationError:
                raise DomainValidationError(
                    "Translation language is invalid",
                    details={"field": "translation.language"},
                ) from None
            if language in languages:
                raise ConflictError("Translation language is duplicated")
            languages.add(language)
            result.append(
                (language, normalize_translated_tag_value(translation.value))
            )
        return result
