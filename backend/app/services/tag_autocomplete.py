from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from backend.app.core.exceptions import DomainValidationError
from backend.app.services.tag_parser import TagDomain, parse_tag_type
from backend.app.services.tag_values import normalize_tag_whitespace


MAX_AUTOCOMPLETE_QUERY_LENGTH = 255
MAX_AUTOCOMPLETE_RESULTS = 20

_TYPE_ABBREVIATIONS = {
    "author": "a",
    "gender": "g",
    "voice": "v",
    "topic": "t",
    "category": "c",
    "other": "o",
}


class TranslationLike(Protocol):
    normalized_value: str


class TagTypeLike(Protocol):
    value: str


class TagLike(Protocol):
    id: int
    type: TagTypeLike
    normalized_value: str
    translations: list[TranslationLike]


@dataclass(frozen=True)
class AutocompleteQuery:
    tag_type: str | None
    normalized_value: str


def parse_autocomplete_query(
    query: object,
    domain: TagDomain,
) -> AutocompleteQuery:
    if not isinstance(query, str):
        raise DomainValidationError(
            "Autocomplete query must be text",
            details={"field": "query"},
        )
    if len(query) > MAX_AUTOCOMPLETE_QUERY_LENGTH:
        raise DomainValidationError(
            "Autocomplete query is too long",
            details={"field": "query"},
        )
    value = query.strip()
    if not value:
        raise DomainValidationError(
            "Autocomplete query cannot be empty",
            details={"field": "query"},
        )
    if value.count(":") > 1:
        raise DomainValidationError(
            "Autocomplete query contains too many colons",
            details={"field": "query"},
        )
    if ":" in value:
        prefix, raw_value = value.split(":", maxsplit=1)
        tag_type = parse_tag_type(prefix, domain).value
        return AutocompleteQuery(
            tag_type=tag_type,
            normalized_value=_normalize_partial_value(raw_value),
        )
    return AutocompleteQuery(
        tag_type=None,
        normalized_value=_normalize_partial_value(value),
    )


def autocomplete_tags(
    tags: Sequence[TagLike],
    *,
    query: object,
    domain: TagDomain,
    limit: int,
) -> list[str]:
    parsed = parse_autocomplete_query(query, domain)
    ranked: list[tuple[int, str, str, int]] = []
    for tag in tags:
        tag_type = tag.type.value
        if parsed.tag_type is not None and tag_type != parsed.tag_type:
            continue
        searchable_values = _searchable_values(tag, parsed.tag_type is None)
        score = _match_score(searchable_values, parsed.normalized_value)
        if score is None:
            continue
        ranked.append((score, tag_type, tag.normalized_value, tag.id))

    ranked.sort()
    return [
        f"{tag_type}:{normalized_value}"
        for _, tag_type, normalized_value, _ in ranked[:limit]
    ]


def _normalize_partial_value(value: str) -> str:
    return normalize_tag_whitespace(value).casefold()


def _searchable_values(tag: TagLike, include_type_prefixes: bool) -> list[str]:
    values = [tag.normalized_value]
    values.extend(translation.normalized_value for translation in tag.translations)
    if include_type_prefixes:
        tag_type = tag.type.value
        abbreviation = _TYPE_ABBREVIATIONS[tag_type]
        values.extend(
            (
                f"{tag_type}:{tag.normalized_value}",
                f"{abbreviation}:{tag.normalized_value}",
            )
        )
    return values


def _match_score(values: list[str], query: str) -> int | None:
    if any(value.startswith(query) for value in values):
        return 0
    if any(query in value for value in values):
        return 1
    return None
