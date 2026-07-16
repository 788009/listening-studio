from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Protocol

from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from backend.app.core.exceptions import DomainValidationError, JobFailedError


MAX_CORPUS_LENGTH = 100_000
MAX_GENERATION_COUNT = 20
_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
SuggestedTag = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"


class LlmModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
    )


class ListeningGenerationRequest(LlmModel):
    corpus: str = Field(min_length=1, max_length=MAX_CORPUS_LENGTH)
    question_types: frozenset[QuestionType] = Field(min_length=1)
    count: int = Field(ge=1, le=MAX_GENERATION_COUNT)
    language: str = Field(default="en", min_length=2, max_length=35)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.replace("_", "-")
        if _LANGUAGE_PATTERN.fullmatch(normalized) is None:
            raise ValueError("Language code is invalid")
        parts = normalized.split("-")
        return "-".join([parts[0].lower(), *parts[1:]])


class GeneratedDialogueTurn(LlmModel):
    speaker: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    text: NonEmptyText


class GeneratedListeningContent(LlmModel):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    turns: list[GeneratedDialogueTurn] = Field(min_length=1)
    question_types: list[QuestionType] = Field(min_length=1)
    suggested_topics: list[SuggestedTag] = Field(min_length=1)
    suggested_categories: list[SuggestedTag] = Field(min_length=1)

    @field_validator(
        "question_types",
        "suggested_topics",
        "suggested_categories",
    )
    @classmethod
    def require_unique_values(cls, value: list[object]) -> list[object]:
        if len(value) != len(set(value)):
            raise ValueError("Generated values must be unique")
        for item in value:
            if isinstance(item, str) and not any(
                character.isalnum() for character in item
            ):
                raise ValueError("Generated values require a letter or number")
        return value


class ListeningGenerationResult(LlmModel):
    items: list[GeneratedListeningContent] = Field(min_length=1)


class ListeningContentGenerator(Protocol):
    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> object:
        pass


class PlaceholderListeningContentGenerator:
    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> ListeningGenerationResult:
        del call_id
        question_types = sorted(request.question_types, key=lambda item: item.value)
        items = [
            GeneratedListeningContent(
                title=f"Listening Practice {index}",
                turns=[
                    GeneratedDialogueTurn(
                        speaker="Host",
                        text="Welcome to today's listening practice.",
                    ),
                    GeneratedDialogueTurn(
                        speaker="Guest",
                        text=(
                            "Clear communication helps learners understand "
                            "new ideas."
                        ),
                    ),
                ],
                question_types=question_types,
                suggested_topics=["education"],
                suggested_categories=["listening_practice"],
            )
            for index in range(1, request.count + 1)
        ]
        return ListeningGenerationResult(items=items)


class ValidatingListeningContentGenerator:
    def __init__(self, implementation: ListeningContentGenerator) -> None:
        self.implementation = implementation

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> ListeningGenerationResult:
        normalized_call_id = self._validate_call_id(call_id)
        question_types = sorted(item.value for item in request.question_types)
        call_logger = logger.bind(request_id=normalized_call_id)
        call_logger.info(
            "Listening content generation requested call_id={} corpus_length={} "
            "question_types={} count={}",
            normalized_call_id,
            len(request.corpus),
            ",".join(question_types),
            request.count,
        )
        try:
            raw_result = self.implementation.generate(
                request,
                call_id=normalized_call_id,
            )
            result = ListeningGenerationResult.model_validate(raw_result)
            self._validate_result(request, result)
        except (ValidationError, ValueError) as exc:
            call_logger.warning(
                "Listening content generation returned invalid output "
                "exception_type={}",
                type(exc).__name__,
            )
            raise JobFailedError(
                "Content generator returned invalid output",
                details={"exceptionType": type(exc).__name__},
            ) from exc
        call_logger.info(
            "Listening content generation completed call_id={} item_count={}",
            normalized_call_id,
            len(result.items),
        )
        return result

    @staticmethod
    def _validate_result(
        request: ListeningGenerationRequest,
        result: ListeningGenerationResult,
    ) -> None:
        if len(result.items) != request.count:
            raise ValueError("Generated item count does not match the request")
        expected_types = set(request.question_types)
        for item in result.items:
            if set(item.question_types) != expected_types:
                raise ValueError(
                    "Generated question types do not match the request"
                )

    @staticmethod
    def _validate_call_id(call_id: str) -> str:
        if not isinstance(call_id, str):
            raise DomainValidationError(
                "Generation call ID is invalid",
                details={"field": "callId"},
            )
        value = call_id.strip()
        if _CALL_ID_PATTERN.fullmatch(value) is None:
            raise DomainValidationError(
                "Generation call ID is invalid",
                details={"field": "callId"},
            )
        return value
