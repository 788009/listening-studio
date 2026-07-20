from __future__ import annotations

import random
import unittest

from pydantic import ValidationError

from backend.app.core.exceptions import JobFailedError
from backend.app.integrations.llm import (
    GeneratedListeningContent,
    ListeningGenerationRequest,
    PlaceholderListeningContentGenerator,
    PlaceholderTopicTagSuggester,
    QuestionType,
    SuggestedTopicTag,
    TopicSuggestionRequest,
    ValidatingListeningContentGenerator,
    ValidatingTopicTagSuggester,
)


class InvalidGenerator:
    def generate(self, request: ListeningGenerationRequest, *, call_id: str) -> object:
        del request, call_id
        return {"items": []}


class InvalidTopicSuggester:
    def suggest(self, request: TopicSuggestionRequest, *, call_id: str) -> object:
        del request, call_id
        return {"topics": [{"english_value": "invalid value"}]}


class LlmIntegrationTest(unittest.TestCase):
    def test_placeholder_loads_examples_and_round_robins_selected_types(self) -> None:
        request = ListeningGenerationRequest(
            corpus="Source corpus",
            question_types={
                QuestionType.SHORT_DIALOGUE,
                QuestionType.LONG_DIALOGUE,
                QuestionType.MONOLOGUE,
            },
            count=7,
        )
        result = PlaceholderListeningContentGenerator().generate(
            request,
            call_id="test-call",
        )

        self.assertEqual(len(result.items), 7)
        self.assertEqual(
            [item.question_type for item in result.items[:3]],
            [
                QuestionType.SHORT_DIALOGUE,
                QuestionType.LONG_DIALOGUE,
                QuestionType.MONOLOGUE,
            ],
        )
        self.assertTrue(all(item.questions for item in result.items))
        self.assertTrue(
            all(
                question.correct_answers and question.incorrect_answers
                for item in result.items
                for question in item.questions
            )
        )

    def test_placeholder_returns_all_available_examples_when_count_is_larger(self) -> None:
        result = ValidatingListeningContentGenerator(
            PlaceholderListeningContentGenerator()
        ).generate(
            ListeningGenerationRequest(
                corpus="Source corpus",
                question_types=set(QuestionType),
                count=20,
            ),
            call_id="all-examples",
        )
        self.assertEqual(len(result.items), 11)

    def test_request_count_must_cover_every_selected_type(self) -> None:
        with self.assertRaises(ValidationError):
            ListeningGenerationRequest(
                corpus="Source corpus",
                question_types=set(QuestionType),
                count=2,
            )

    def test_dialogue_and_monologue_speaker_shapes_are_enforced(self) -> None:
        dialogue = {
            "question_type": "short_dialogue",
            "title": "Invalid",
            "utterances": [{"speaker": "Man", "text": "Only one role"}],
            "questions": [
                {
                    "prompt": "Question?",
                    "correct_answers": ["Yes"],
                    "incorrect_answers": ["No"],
                }
            ],
        }
        with self.assertRaises(ValidationError):
            GeneratedListeningContent.model_validate(dialogue)

        monologue = dict(dialogue)
        monologue["question_type"] = "monologue"
        monologue["utterances"] = [
            {"speaker": "Man", "text": "First"},
            {"speaker": "Woman", "text": "Second"},
        ]
        with self.assertRaises(ValidationError):
            GeneratedListeningContent.model_validate(monologue)

    def test_placeholder_topic_suggester_selects_existing_topic(self) -> None:
        result = PlaceholderTopicTagSuggester(random.Random(4)).suggest(
            TopicSuggestionRequest(
                corpus="Source corpus",
                existing_topics=("education", "travel"),
            ),
            call_id="topics",
        )
        self.assertEqual(len(result.topics), 1)
        self.assertIn(result.topics[0].english_value, {"education", "travel"})

    def test_topic_protocol_allows_new_normalized_tags(self) -> None:
        tag = SuggestedTopicTag.model_validate(
            {
                "english_value": "climate_change",
                "translations": [{"language": "zh-CN", "value": "气候变化"}],
            }
        )
        self.assertEqual(tag.english_value, "climate_change")

    def test_validators_reject_invalid_implementation_output(self) -> None:
        with self.assertRaises(JobFailedError):
            ValidatingListeningContentGenerator(InvalidGenerator()).generate(
                ListeningGenerationRequest(
                    corpus="Source corpus",
                    question_types={QuestionType.MONOLOGUE},
                    count=1,
                ),
                call_id="invalid-content",
            )
        with self.assertRaises(JobFailedError):
            ValidatingTopicTagSuggester(InvalidTopicSuggester()).suggest(
                TopicSuggestionRequest(corpus="Source corpus", existing_topics=()),
                call_id="invalid-topic",
            )


if __name__ == "__main__":
    unittest.main()
