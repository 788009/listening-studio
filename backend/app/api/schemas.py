from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, Field, NonNegativeInt
from pydantic.types import StringConstraints


MAX_PAGE_SIZE = 100
MAX_TITLE_LENGTH = 200
_LANGUAGE_CODE_PATTERN = re.compile(
    r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"
)


def _normalize_language_code(value: object) -> object:
    if not isinstance(value, str):
        return value

    normalized = value.strip().replace("_", "-")
    if not _LANGUAGE_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid language code")

    parts = normalized.split("-")
    result = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            result.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (
            len(part) == 3 and part.isdigit()
        ):
            result.append(part.upper())
        else:
            result.append(part.lower())
    return "-".join(result)


def _reject_boolean_id(value: object) -> object:
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid resource IDs")
    return value


Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
    ),
]
LanguageCode = Annotated[str, BeforeValidator(_normalize_language_code)]
ResourceId = Annotated[int, BeforeValidator(_reject_boolean_id), Field(gt=0)]


class Visibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


ItemT = TypeVar("ItemT")


class PaginatedResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)
    total: NonNegativeInt
