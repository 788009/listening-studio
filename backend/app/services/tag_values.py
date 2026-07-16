from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from backend.app.api.schemas import LanguageCode
from backend.app.core.exceptions import ConflictError, DomainValidationError


_WHITESPACE = re.compile(r"\s+")
_ENGLISH_VALUE = re.compile(r"^(?=.*[A-Za-z0-9])[A-Za-z0-9_-]+$")
MAX_TAG_VALUE_LENGTH = 255
_LANGUAGE_CODE_ADAPTER = TypeAdapter(LanguageCode)


@dataclass(frozen=True)
class NormalizedTagValue:
    value: str
    normalized_value: str


@dataclass(frozen=True)
class TagTranslationInput:
    language: str
    value: str


@dataclass(frozen=True)
class NormalizedTagTranslation:
    language: str
    value: NormalizedTagValue


def _canonical_value(raw_value: object, field: str) -> str:
    if not isinstance(raw_value, str):
        raise DomainValidationError(
            "Tag value is required",
            details={"field": field},
        )
    value = normalize_tag_whitespace(raw_value)
    if not value:
        raise DomainValidationError(
            "Tag value cannot be empty",
            details={"field": field},
        )
    if ":" in value:
        raise DomainValidationError(
            "Tag values cannot contain colons",
            details={"field": field},
        )
    if len(value) > MAX_TAG_VALUE_LENGTH:
        raise DomainValidationError(
            "Tag value is too long",
            details={"field": field},
        )
    return value


def normalize_tag_whitespace(raw_value: str) -> str:
    value = unicodedata.normalize("NFKC", raw_value.strip())
    return _WHITESPACE.sub("_", value)


def display_tag_value(value: str) -> str:
    return value.replace("_", " ")


def select_tag_display_value(
    english_value: str,
    translations: Mapping[str, str],
    language: str,
) -> str:
    normalized_translations = {
        _language_key(code): value for code, value in translations.items()
    }
    requested_language = _language_key(language)
    candidates = [requested_language]
    if "-" in requested_language:
        candidates.append(requested_language.split("-", maxsplit=1)[0])

    for candidate in candidates:
        translated_value = normalized_translations.get(candidate)
        if translated_value is not None:
            return display_tag_value(translated_value)
    return display_tag_value(english_value)


def _language_key(language: str) -> str:
    return unicodedata.normalize("NFKC", language.strip()).replace("_", "-").casefold()


def normalize_english_tag_value(raw_value: object) -> NormalizedTagValue:
    value = _canonical_value(raw_value, "value")
    if not _ENGLISH_VALUE.fullmatch(value):
        raise DomainValidationError(
            "English tag values allow only ASCII letters, numbers, "
            "underscores, and hyphens",
            details={"field": "value"},
        )
    return NormalizedTagValue(value=value, normalized_value=value.lower())


def normalize_translated_tag_value(raw_value: object) -> NormalizedTagValue:
    value = _canonical_value(raw_value, "translation.value")
    has_letter_or_number = False
    for character in value:
        if character.isalnum():
            has_letter_or_number = True
            continue
        if character not in {"_", "-"}:
            raise DomainValidationError(
                "Translated tag values allow only letters, numbers, "
                "underscores, and hyphens",
                details={"field": "translation.value"},
            )
    if not has_letter_or_number:
        raise DomainValidationError(
            "Translated tag values require a letter or number",
            details={"field": "translation.value"},
        )
    return NormalizedTagValue(
        value=value,
        normalized_value=value.casefold(),
    )


def normalize_tag_translations(
    translations: Iterable[TagTranslationInput],
) -> list[NormalizedTagTranslation]:
    result: list[NormalizedTagTranslation] = []
    languages: set[str] = set()
    for translation in translations:
        try:
            language = _LANGUAGE_CODE_ADAPTER.validate_python(translation.language)
        except ValidationError:
            raise DomainValidationError(
                "Translation language is invalid",
                details={"field": "translation.language"},
            ) from None
        if language in languages:
            raise ConflictError("Translation language is duplicated")
        languages.add(language)
        result.append(
            NormalizedTagTranslation(
                language=language,
                value=normalize_translated_tag_value(translation.value),
            )
        )
    return result
