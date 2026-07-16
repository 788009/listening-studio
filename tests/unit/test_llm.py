from __future__ import annotations

import unittest

from loguru import logger
from pydantic import ValidationError

from backend.app.core.exceptions import DomainValidationError, JobFailedError
from backend.app.integrations.llm import (
    GeneratedDialogueTurn,
    GeneratedListeningContent,
    ListeningGenerationResult,
    ListeningGenerationRequest,
    PlaceholderListeningContentGenerator,
    QuestionType,
    ValidatingListeningContentGenerator,
)


class InvalidGenerator:
    def __init__(self, output: object) -> None:
        self.output = output

    def generate(
        self,
        request: ListeningGenerationRequest,
        *,
        call_id: str,
    ) -> object:
        del request, call_id
        return self.output


class LlmIntegrationTest(unittest.TestCase):
    def test_placeholder_is_deterministic_valid_and_logs_only_metadata(self) -> None:
        corpus = "Private corpus content that must not be logged."
        request = ListeningGenerationRequest(
            corpus=corpus,
            question_types={
                QuestionType.MULTIPLE_CHOICE,
                QuestionType.SHORT_ANSWER,
            },
            count=3,
            language="en-US",
        )
        generator = ValidatingListeningContentGenerator(
            PlaceholderListeningContentGenerator()
        )
        messages: list[str] = []
        sink_id = logger.add(messages.append, format="{message}")
        try:
            first = generator.generate(request, call_id="corpus-job-12")
            second = generator.generate(request, call_id="corpus-job-12")
        finally:
            logger.remove(sink_id)

        self.assertEqual(first, second)
        self.assertEqual(len(first.items), 3)
        self.assertEqual(
            set(first.items[0].question_types),
            set(request.question_types),
        )
        log_text = "".join(messages)
        self.assertIn("call_id=corpus-job-12", log_text)
        self.assertIn(f"corpus_length={len(corpus)}", log_text)
        self.assertIn("count=3", log_text)
        self.assertNotIn(corpus, log_text)

    def test_request_rejects_invalid_corpus_count_type_and_language(self) -> None:
        valid = {
            "corpus": "Corpus",
            "question_types": [QuestionType.TRUE_FALSE],
            "count": 1,
            "language": "en",
        }
        invalid_values = [
            {**valid, "corpus": "   "},
            {**valid, "count": 0},
            {**valid, "count": 21},
            {**valid, "question_types": ["unknown"]},
            {**valid, "question_types": []},
            {**valid, "language": "not a language"},
        ]

        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ListeningGenerationRequest.model_validate(value)

    def test_invalid_implementation_output_fails_at_validation_boundary(self) -> None:
        request = ListeningGenerationRequest(
            corpus="Corpus",
            question_types={QuestionType.MULTIPLE_CHOICE},
            count=2,
            language="en",
        )
        valid_item = GeneratedListeningContent(
            title="Title",
            turns=[GeneratedDialogueTurn(speaker="Host", text="Text")],
            question_types=[QuestionType.MULTIPLE_CHOICE],
            suggested_topics=["education"],
            suggested_categories=["practice"],
        )
        invalid_outputs = [
            {"items": [valid_item]},
            {
                "items": [
                    valid_item,
                    valid_item.model_copy(
                        update={"question_types": [QuestionType.TRUE_FALSE]}
                    ),
                ]
            },
            {
                "items": [
                    valid_item,
                    {
                        "title": "Broken",
                        "turns": [],
                        "question_types": ["multiple_choice"],
                        "suggested_topics": ["invalid topic"],
                        "suggested_categories": ["practice"],
                    },
                ]
            },
            ListeningGenerationResult.model_construct(
                items=[
                    GeneratedListeningContent.model_construct(
                        title="",
                        turns=[],
                        question_types=[],
                        suggested_topics=[],
                        suggested_categories=[],
                    ),
                    valid_item,
                ]
            ),
        ]

        for output in invalid_outputs:
            with self.subTest(output=output), self.assertRaises(JobFailedError):
                ValidatingListeningContentGenerator(
                    InvalidGenerator(output)
                ).generate(request, call_id="job-1")

    def test_call_id_is_validated_before_implementation_runs(self) -> None:
        request = ListeningGenerationRequest(
            corpus="Corpus",
            question_types={QuestionType.TRUE_FALSE},
            count=1,
        )
        generator = ValidatingListeningContentGenerator(
            PlaceholderListeningContentGenerator()
        )

        with self.assertRaises(DomainValidationError):
            generator.generate(request, call_id="invalid call id")


if __name__ == "__main__":
    unittest.main()
