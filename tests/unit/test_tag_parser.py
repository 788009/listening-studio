from __future__ import annotations

import unittest

from backend.app.core.exceptions import DomainValidationError
from backend.app.services.tag_parser import (
    MAX_QUERY_LENGTH,
    MAX_QUERY_TOKEN_LENGTH,
    ParsedQuery,
    ParsedTagTerm,
    TagDomain,
    TagType,
    parse_search_query,
    parse_tag_term,
    parse_tag_type,
)
from backend.app.services.tag_values import (
    display_tag_value,
    normalize_english_tag_value,
    normalize_tag_whitespace,
    select_tag_display_value,
)


class TagValueRuleTest(unittest.TestCase):
    def test_whitespace_english_and_display_normalization(self) -> None:
        self.assertEqual(
            normalize_tag_whitespace("  Climate\t  Change  "),
            "Climate_Change",
        )
        normalized = normalize_english_tag_value("  Climate   Change ")
        self.assertEqual(normalized.value, "Climate_Change")
        self.assertEqual(normalized.normalized_value, "climate_change")
        self.assertEqual(display_tag_value("climate_change"), "climate change")

    def test_language_selection_and_english_fallback(self) -> None:
        translations = {
            "zh": "气候_变化",
            "fr-FR": "changement_climatique",
        }

        self.assertEqual(
            select_tag_display_value("climate_change", translations, "zh-CN"),
            "气候 变化",
        )
        self.assertEqual(
            select_tag_display_value("climate_change", translations, "fr_fr"),
            "changement climatique",
        )
        self.assertEqual(
            select_tag_display_value("climate_change", translations, "de"),
            "climate change",
        )


class TagParserTest(unittest.TestCase):
    def test_full_and_abbreviated_types_are_case_insensitive(self) -> None:
        cases = [
            ("AUTHOR", TagDomain.VOICE, TagType.AUTHOR),
            ("a", TagDomain.AUDIO, TagType.AUTHOR),
            ("Gender", TagDomain.VOICE, TagType.GENDER),
            ("S", TagDomain.AUDIO, TagType.SPEAKER),
            ("topic", TagDomain.AUDIO, TagType.TOPIC),
            ("C", TagDomain.AUDIO, TagType.CATEGORY),
        ]

        for prefix, domain, expected in cases:
            with self.subTest(prefix=prefix, domain=domain):
                self.assertEqual(parse_tag_type(prefix, domain), expected)

    def test_domain_rejects_types_from_other_tag_system(self) -> None:
        for token, domain in (
            ("speaker:teacher", TagDomain.VOICE),
            ("g:male", TagDomain.AUDIO),
            ("topic:climate", TagDomain.VOICE),
        ):
            with self.subTest(token=token), self.assertRaises(
                DomainValidationError
            ):
                parse_tag_term(token, domain)

    def test_tag_term_normalizes_english_and_multilingual_values(self) -> None:
        self.assertEqual(
            parse_tag_term("G:Female_Voice", "voice"),
            ParsedTagTerm(
                type=TagType.GENDER,
                normalized_value="female_voice",
            ),
        )
        self.assertEqual(
            parse_tag_term("topic:气候_变化", "audio"),
            ParsedTagTerm(
                type=TagType.TOPIC,
                normalized_value="气候_变化",
            ),
        )

    def test_query_is_split_into_tag_terms_and_keywords(self) -> None:
        query = parse_search_query(
            "  topic:Climate_Change   SPEAKER:Teacher  Arctic   气候  ",
            TagDomain.AUDIO,
        )

        self.assertEqual(
            query,
            ParsedQuery(
                tag_terms=(
                    ParsedTagTerm(TagType.TOPIC, "climate_change"),
                    ParsedTagTerm(TagType.SPEAKER, "teacher"),
                ),
                keywords=("arctic", "气候"),
            ),
        )

    def test_keywords_remain_data_and_are_not_sql_expressions(self) -> None:
        query = parse_search_query(r"100% name_with_under \\path", "audio")

        self.assertEqual(
            query.keywords,
            ("100%", "name_with_under", r"\\path"),
        )

    def test_invalid_tag_syntax_is_rejected(self) -> None:
        invalid_tokens = [
            "unknown:value",
            "topic:",
            ":value",
            "topic:value:extra",
            "topic",
            "",
            f"topic:{'a' * MAX_QUERY_TOKEN_LENGTH}",
        ]

        for token in invalid_tokens:
            with self.subTest(token=token), self.assertRaises(
                DomainValidationError
            ):
                parse_tag_term(token, TagDomain.AUDIO)

    def test_empty_unknown_domain_and_long_queries_are_rejected(self) -> None:
        invalid_queries: list[tuple[object, object]] = [
            (None, TagDomain.AUDIO),
            ("", TagDomain.AUDIO),
            ("   ", TagDomain.AUDIO),
            ("topic:climate", "video"),
            ("a" * (MAX_QUERY_LENGTH + 1), TagDomain.AUDIO),
        ]

        for query, domain in invalid_queries:
            with self.subTest(query=query, domain=domain), self.assertRaises(
                DomainValidationError
            ):
                parse_search_query(query, domain)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
