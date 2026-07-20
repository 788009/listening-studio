from __future__ import annotations

import json
import random
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Protocol

from loguru import logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.app.core.exceptions import DomainValidationError, JobFailedError


MAX_CORPUS_LENGTH = 100_000
MAX_GENERATION_COUNT = 20
_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_EXAMPLE_DIRECTORY = Path(__file__).resolve().parents[3] / "category_examples"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
SuggestedTagValue = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class QuestionType(str, Enum):
    SHORT_DIALOGUE = "short_dialogue"
    LONG_DIALOGUE = "long_dialogue"
    MONOLOGUE = "monologue"


_QUESTION_TYPE_ORDER = {
    QuestionType.SHORT_DIALOGUE: 0,
    QuestionType.LONG_DIALOGUE: 1,
    QuestionType.MONOLOGUE: 2,
}
_EXAMPLE_FILES = {
    QuestionType.SHORT_DIALOGUE: "short.json",
    QuestionType.LONG_DIALOGUE: "long.json",
    QuestionType.MONOLOGUE: "monologue.json",
}


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
        return _normalize_language(value)

    @model_validator(mode="after")
    def require_one_result_per_selected_type(self) -> ListeningGenerationRequest:
        if self.count < len(self.question_types):
            raise ValueError("Count must cover every selected question type")
        return self


class GeneratedDialogueTurn(LlmModel):
    speaker: Literal["Man", "Woman"]
    text: NonEmptyText


class GeneratedQuestion(LlmModel):
    prompt: NonEmptyText
    correct_answers: list[NonEmptyText] = Field(min_length=1)
    incorrect_answers: list[NonEmptyText] = Field(min_length=1)


class GeneratedListeningContent(LlmModel):
    question_type: QuestionType
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    utterances: list[GeneratedDialogueTurn] = Field(min_length=1)
    questions: list[GeneratedQuestion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_speaker_shape(self) -> GeneratedListeningContent:
        speakers = {utterance.speaker for utterance in self.utterances}
        if self.question_type is QuestionType.MONOLOGUE:
            if len(speakers) != 1:
                raise ValueError("A monologue must use one speaker")
        elif speakers != {"Man", "Woman"}:
            raise ValueError("A dialogue must use Man and Woman")
        return self


class ListeningGenerationResult(LlmModel):
    items: list[GeneratedListeningContent] = Field(min_length=1)


class GeneratedTagTranslation(LlmModel):
    language: str = Field(min_length=2, max_length=35)
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _normalize_language(value)


class SuggestedTopicTag(LlmModel):
    english_value: SuggestedTagValue
    translations: list[GeneratedTagTranslation] = Field(default_factory=list)

    @field_validator("translations")
    @classmethod
    def require_unique_languages(
        cls,
        values: list[GeneratedTagTranslation],
    ) -> list[GeneratedTagTranslation]:
        if len({item.language for item in values}) != len(values):
            raise ValueError("Suggested tag translation languages must be unique")
        return values


class TopicSuggestionRequest(LlmModel):
    corpus: str = Field(min_length=1, max_length=MAX_CORPUS_LENGTH)
    existing_topics: tuple[SuggestedTagValue, ...]
    language: str = Field(default="en", min_length=2, max_length=35)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        return _normalize_language(value)


class TopicSuggestionResult(LlmModel):
    topics: list[SuggestedTopicTag] = Field(default_factory=list, max_length=10)

    @field_validator("topics")
    @classmethod
    def require_unique_topics(
        cls,
        values: list[SuggestedTopicTag],
    ) -> list[SuggestedTopicTag]:
        normalized = [item.english_value.casefold() for item in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Suggested topics must be unique")
        return values


class ListeningContentGenerator(Protocol):
    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> object:
        pass


class TopicTagSuggester(Protocol):
    def suggest(
        self,
        request: TopicSuggestionRequest,
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
        selected = sorted(
            request.question_types,
            key=_QUESTION_TYPE_ORDER.__getitem__,
        )
        examples = {item: list(_load_examples(item)) for item in selected}
        items: list[GeneratedListeningContent] = []
        position = 0
        while len(items) < request.count:
            added = False
            for question_type in selected:
                values = examples[question_type]
                if position < len(values):
                    items.append(values[position])
                    added = True
                    if len(items) == request.count:
                        break
            if not added:
                break
            position += 1
        return ListeningGenerationResult(items=items)


class PlaceholderTopicTagSuggester:
    def __init__(self, rng: random.Random | random.SystemRandom | None = None) -> None:
        self.rng = rng or random.SystemRandom()

    def suggest(
        self,
        request: TopicSuggestionRequest,
        *,
        call_id: str,
    ) -> TopicSuggestionResult:
        del call_id
        if not request.existing_topics:
            return TopicSuggestionResult()
        return TopicSuggestionResult(
            topics=[
                SuggestedTopicTag(
                    english_value=self.rng.choice(request.existing_topics),
                )
            ]
        )


class ValidatingListeningContentGenerator:
    def __init__(self, implementation: ListeningContentGenerator) -> None:
        self.implementation = implementation

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> ListeningGenerationResult:
        normalized_call_id = _validate_call_id(call_id)
        call_logger = logger.bind(request_id=normalized_call_id)
        call_logger.info(
            "Listening content generation requested call_id={} corpus_length={} "
            "question_types={} count={}",
            normalized_call_id,
            len(request.corpus),
            ",".join(sorted(item.value for item in request.question_types)),
            request.count,
        )
        try:
            result = ListeningGenerationResult.model_validate(
                self.implementation.generate(request, call_id=normalized_call_id)
            )
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
        if len(result.items) > request.count:
            raise ValueError("Generated item count exceeds the request")
        generated_types = {item.question_type for item in result.items}
        if generated_types != set(request.question_types):
            raise ValueError("Generated question types do not match the request")


class ValidatingTopicTagSuggester:
    def __init__(self, implementation: TopicTagSuggester) -> None:
        self.implementation = implementation

    def suggest(
        self,
        request: TopicSuggestionRequest,
        *,
        call_id: str,
    ) -> TopicSuggestionResult:
        normalized_call_id = _validate_call_id(call_id)
        call_logger = logger.bind(request_id=normalized_call_id)
        call_logger.info(
            "Topic suggestion requested call_id={} corpus_length={} "
            "existing_topic_count={}",
            normalized_call_id,
            len(request.corpus),
            len(request.existing_topics),
        )
        try:
            result = TopicSuggestionResult.model_validate(
                self.implementation.suggest(request, call_id=normalized_call_id)
            )
        except (ValidationError, ValueError) as exc:
            call_logger.warning(
                "Topic suggestion returned invalid output exception_type={}",
                type(exc).__name__,
            )
            raise JobFailedError(
                "Topic suggester returned invalid output",
                details={"exceptionType": type(exc).__name__},
            ) from exc
        call_logger.info(
            "Topic suggestion completed call_id={} suggestion_count={}",
            normalized_call_id,
            len(result.topics),
        )
        return result


@lru_cache(maxsize=3)
def _load_examples(question_type: QuestionType) -> tuple[GeneratedListeningContent, ...]:
    path = _EXAMPLE_DIRECTORY / _EXAMPLE_FILES[question_type]
    try:
        raw_items = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            GeneratedListeningContent(
                question_type=question_type,
                title=item["title"],
                utterances=[
                    GeneratedDialogueTurn(
                        speaker=utterance["speaker"],
                        text=utterance["text"],
                    )
                    for utterance in item["utterances"]
                ],
                questions=[
                    GeneratedQuestion(
                        prompt=question["prompt"],
                        correct_answers=question["correctAnswers"],
                        incorrect_answers=question["wrongAnswers"],
                    )
                    for question in item["questions"]
                ],
            )
            for item in raw_items
        )
    except (OSError, TypeError, ValueError, KeyError, ValidationError) as exc:
        raise RuntimeError(f"Question examples are invalid: {path.name}") from exc


def _normalize_language(value: str) -> str:
    normalized = value.replace("_", "-")
    if _LANGUAGE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Language code is invalid")
    parts = normalized.split("-")
    return "-".join([parts[0].lower(), *parts[1:]])


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
