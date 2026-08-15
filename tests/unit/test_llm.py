from __future__ import annotations

import json
import random
import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from backend.app.core.exceptions import JobFailedError
from backend.app.integrations.llm import (
    DashScopeLlmIntegration,
    DraftRevisionRequest,
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


def completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class FakeCompletions:
    def __init__(self, effects: list[object]) -> None:
        self.effects = list(effects)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class FakeOpenAI:
    def __init__(self, effects: list[object]) -> None:
        self.completions = FakeCompletions(effects)
        self.chat = SimpleNamespace(completions=self.completions)


class InvalidGenerator:
    def generate(self, request: ListeningGenerationRequest, *, call_id: str) -> object:
        del request, call_id
        return {"items": []}


class InvalidTopicSuggester:
    def suggest(self, request: TopicSuggestionRequest, *, call_id: str) -> object:
        del request, call_id
        return {"topics": [{"english_value": "invalid value"}]}


class LlmIntegrationTest(unittest.TestCase):
    def test_placeholder_uses_requested_question_type_count(self) -> None:
        request = ListeningGenerationRequest(
            corpus="Source corpus",
            question_type_counts={QuestionType.SHORT_DIALOGUE: 7},
        )
        result = PlaceholderListeningContentGenerator().generate(
            request,
            call_id="test-call",
        )

        self.assertEqual(len(result.items), 7)
        self.assertTrue(
            all(
                item.question_type is QuestionType.SHORT_DIALOGUE
                for item in result.items
            )
        )
        self.assertEqual(len({item.title for item in result.items}), 7)
        self.assertTrue(all(item.questions for item in result.items))
        self.assertTrue(
            all(
                question.correct_answers and question.incorrect_answers
                for item in result.items
                for question in item.questions
            )
        )

    def test_request_rejects_multiple_question_types(self) -> None:
        with self.assertRaises(ValidationError):
            ListeningGenerationRequest(
                corpus="Source corpus",
                question_type_counts={
                    QuestionType.SHORT_DIALOGUE: 1,
                    QuestionType.MONOLOGUE: 1,
                },
            )

    def test_request_rejects_total_count_above_limit(self) -> None:
        with self.assertRaises(ValidationError):
            ListeningGenerationRequest(
                corpus="Source corpus",
                question_type_counts={
                    QuestionType.SHORT_DIALOGUE: 19,
                    QuestionType.MONOLOGUE: 2,
                },
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
                    question_type_counts={QuestionType.MONOLOGUE: 1},
                ),
                call_id="invalid-content",
            )
        with self.assertRaises(JobFailedError):
            ValidatingTopicTagSuggester(InvalidTopicSuggester()).suggest(
                TopicSuggestionRequest(corpus="Source corpus", existing_topics=()),
                call_id="invalid-topic",
            )

    def test_dashscope_content_uses_prompt_material_and_strict_json(self) -> None:
        payload = {
            "items": [
                {
                    "title": "Community Garden Plan",
                    "utterances": [
                        {"speaker": "Man", "text": "Where should we plant herbs?"},
                        {
                            "speaker": "Woman",
                            "text": "Near the entrance where volunteers can water them.",
                        },
                    ],
                    "questions": [
                        {
                            "prompt": "Where will the herbs be planted?",
                            "correctAnswers": ["Near the entrance."],
                            "wrongAnswers": ["Behind the school.", "Beside the road."],
                        }
                    ],
                }
            ]
        }
        fake = FakeOpenAI([completion(json.dumps(payload))])
        integration = DashScopeLlmIntegration(
            api_key="secret",
            base_url="https://example.invalid/v1",
            model="test-model",
            client=fake,  # type: ignore[arg-type]
            sleep=lambda _: None,
        )

        result = integration.generate(
            ListeningGenerationRequest(
                corpus="A corpus about community gardens",
                question_type_counts={QuestionType.SHORT_DIALOGUE: 1},
            ),
            call_id="content-test",
        )

        self.assertEqual(result.items[0].title, "Community Garden Plan")
        self.assertEqual(result.items[0].question_type, QuestionType.SHORT_DIALOGUE)
        call = fake.completions.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["response_format"], {"type": "json_object"})
        messages = call["messages"]
        assert isinstance(messages, list)
        user_prompt = messages[1]["content"]
        self.assertIn("# 短对话", user_prompt)
        self.assertIn('"Finding a Parking Space"', user_prompt)
        self.assertIn("A corpus about community gardens", user_prompt)

    def test_dashscope_revises_a_draft_and_requires_the_original_speakers(self) -> None:
        revised_payload = {
            "title": "A More Formal Meeting",
            "utterances": [
                {"speakerDisplayName": "Host", "text": "Welcome to the meeting."},
                {"speakerDisplayName": "Guest", "text": "Thank you for inviting me."},
            ],
            "questions": [
                {
                    "prompt": "Why is the guest speaking?",
                    "correctAnswers": ["The guest was invited."],
                    "incorrectAnswers": ["The guest is lost."],
                }
            ],
        }
        fake = FakeOpenAI([completion(json.dumps(revised_payload))])
        integration = DashScopeLlmIntegration(
            api_key="secret",
            base_url="https://example.invalid/v1",
            model="test-model",
            client=fake,  # type: ignore[arg-type]
            sleep=lambda _: None,
        )

        result = integration.revise_draft(
            DraftRevisionRequest(
                prompt="Make the language more formal.",
                question_type=QuestionType.SHORT_DIALOGUE,
                title="Meeting",
                utterances=[
                    {"speakerDisplayName": "Host", "text": "Hi."},
                    {"speakerDisplayName": "Guest", "text": "Hello."},
                ],
                questions=[
                    {
                        "prompt": "Why?",
                        "correctAnswers": ["Invitation"],
                        "incorrectAnswers": ["Accident"],
                    }
                ],
            ),
            call_id="revision-test",
        )

        self.assertEqual(result.title, "A More Formal Meeting")
        call = fake.completions.calls[0]
        self.assertIn(
            "Make the language more formal.", call["messages"][1]["content"]
        )
        self.assertIn(
            'exact list and no other speaker names: ["Guest", "Host"]',
            call["messages"][1]["content"],
        )

    def test_dashscope_retries_three_times_for_any_response_error(self) -> None:
        valid = completion(
            json.dumps(
                {
                    "topics": [
                        {
                            "english_value": "community_gardens",
                            "translations": [
                                {"language": "zh-CN", "value": "社区花园"}
                            ],
                        }
                    ]
                }
            )
        )
        fake = FakeOpenAI(
            [
                RuntimeError("network"),
                completion("not-json"),
                completion('{"topics":[]}'),
                valid,
            ]
        )
        delays: list[float] = []
        integration = DashScopeLlmIntegration(
            api_key="secret",
            base_url="https://example.invalid/v1",
            model="test-model",
            client=fake,  # type: ignore[arg-type]
            sleep=delays.append,
        )

        result = integration.suggest(
            TopicSuggestionRequest(
                corpus="Community gardening source material",
                existing_topics=("education",),
            ),
            call_id="topic-retry",
        )

        self.assertEqual(result.topics[0].english_value, "community_gardens")
        self.assertEqual(len(fake.completions.calls), 4)
        self.assertEqual(delays, [1.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
