from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from backend.app.core.exceptions import DomainValidationError
from backend.app.services.tag_values import normalize_translated_tag_value


MAX_QUERY_LENGTH = 1024
MAX_QUERY_TOKEN_LENGTH = 255
MAX_QUERY_TOKENS = 32


class TagDomain(str, Enum):
    VOICE = "voice"
    AUDIO = "audio"


class TagType(str, Enum):
    AUTHOR = "author"
    GENDER = "gender"
    SPEAKER = "speaker"
    TOPIC = "topic"
    CATEGORY = "category"


_TYPE_ALIASES = {
    "author": TagType.AUTHOR,
    "a": TagType.AUTHOR,
    "gender": TagType.GENDER,
    "g": TagType.GENDER,
    "speaker": TagType.SPEAKER,
    "s": TagType.SPEAKER,
    "topic": TagType.TOPIC,
    "t": TagType.TOPIC,
    "category": TagType.CATEGORY,
    "c": TagType.CATEGORY,
}
_DOMAIN_TYPES = {
    TagDomain.VOICE: {TagType.AUTHOR, TagType.GENDER},
    TagDomain.AUDIO: {
        TagType.AUTHOR,
        TagType.SPEAKER,
        TagType.TOPIC,
        TagType.CATEGORY,
    },
}


@dataclass(frozen=True)
class ParsedTagTerm:
    type: TagType
    normalized_value: str


@dataclass(frozen=True)
class ParsedQuery:
    tag_terms: tuple[ParsedTagTerm, ...]
    keywords: tuple[str, ...]


def parse_tag_type(prefix: str, domain: TagDomain | str) -> TagType:
    parsed_domain = _parse_domain(domain)
    if not isinstance(prefix, str) or not prefix:
        raise DomainValidationError(
            "Tag type prefix is required",
            details={"field": "query"},
        )
    tag_type = _TYPE_ALIASES.get(prefix.casefold())
    if tag_type is None:
        raise DomainValidationError(
            "Unknown tag type prefix",
            details={"field": "query"},
        )
    if tag_type not in _DOMAIN_TYPES[parsed_domain]:
        raise DomainValidationError(
            "Tag type is not valid for this resource domain",
            details={"field": "query"},
        )
    return tag_type


def parse_tag_term(token: str, domain: TagDomain | str) -> ParsedTagTerm:
    if not isinstance(token, str) or not token:
        raise DomainValidationError(
            "Tag term cannot be empty",
            details={"field": "query"},
        )
    if len(token) > MAX_QUERY_TOKEN_LENGTH:
        raise DomainValidationError(
            "Tag term is too long",
            details={"field": "query"},
        )
    if token.count(":") != 1:
        raise DomainValidationError(
            "Tag term must contain exactly one colon",
            details={"field": "query"},
        )

    prefix, value = token.split(":", maxsplit=1)
    if not prefix or not value:
        raise DomainValidationError(
            "Tag type and value are required",
            details={"field": "query"},
        )
    tag_type = parse_tag_type(prefix, domain)
    normalized = normalize_translated_tag_value(value)
    return ParsedTagTerm(type=tag_type, normalized_value=normalized.normalized_value)


def parse_search_query(query: object, domain: TagDomain | str) -> ParsedQuery:
    parsed_domain = _parse_domain(domain)
    if not isinstance(query, str):
        raise DomainValidationError(
            "Search query must be text",
            details={"field": "query"},
        )
    if len(query) > MAX_QUERY_LENGTH:
        raise DomainValidationError(
            "Search query is too long",
            details={"field": "query"},
        )

    tokens = query.split()
    if not tokens:
        raise DomainValidationError(
            "Search query cannot be empty",
            details={"field": "query"},
        )
    if len(tokens) > MAX_QUERY_TOKENS:
        raise DomainValidationError(
            "Search query contains too many terms",
            details={"field": "query", "maxTerms": MAX_QUERY_TOKENS},
        )

    tag_terms: list[ParsedTagTerm] = []
    keywords: list[str] = []
    for token in tokens:
        if len(token) > MAX_QUERY_TOKEN_LENGTH:
            raise DomainValidationError(
                "Search term is too long",
                details={"field": "query"},
            )
        if ":" in token:
            tag_terms.append(parse_tag_term(token, parsed_domain))
        else:
            keywords.append(unicodedata.normalize("NFKC", token).casefold())

    return ParsedQuery(tag_terms=tuple(tag_terms), keywords=tuple(keywords))


def _parse_domain(domain: TagDomain | str) -> TagDomain:
    try:
        return domain if isinstance(domain, TagDomain) else TagDomain(domain.casefold())
    except (AttributeError, ValueError):
        raise DomainValidationError(
            "Unknown tag resource domain",
            details={"field": "domain"},
        ) from None
