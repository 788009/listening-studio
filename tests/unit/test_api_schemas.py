from __future__ import annotations

import unittest

from pydantic import TypeAdapter, ValidationError

from backend.app.api.schemas import (
    LanguageCode,
    PaginatedResponse,
    PaginationParams,
    ResourceId,
    Title,
    Visibility,
)


class ApiSchemasTest(unittest.TestCase):
    def test_title_is_trimmed_and_bounded(self) -> None:
        adapter = TypeAdapter(Title)

        self.assertEqual(adapter.validate_python("  Lesson title  "), "Lesson title")
        with self.assertRaises(ValidationError):
            adapter.validate_python("   ")
        with self.assertRaises(ValidationError):
            adapter.validate_python("x" * 201)

    def test_language_code_is_normalized(self) -> None:
        adapter = TypeAdapter(LanguageCode)

        self.assertEqual(adapter.validate_python("EN_us"), "en-US")
        self.assertEqual(adapter.validate_python("zh-hans-cn"), "zh-Hans-CN")
        with self.assertRaises(ValidationError):
            adapter.validate_python("not a language")

    def test_resource_id_is_a_positive_integer(self) -> None:
        adapter = TypeAdapter(ResourceId)

        self.assertEqual(adapter.validate_python("12"), 12)
        for value in (0, -1, True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                adapter.validate_python(value)

    def test_visibility_has_only_supported_values(self) -> None:
        adapter = TypeAdapter(Visibility)

        self.assertEqual(adapter.validate_python("private"), Visibility.PRIVATE)
        self.assertEqual(adapter.validate_python("public"), Visibility.PUBLIC)
        with self.assertRaises(ValidationError):
            adapter.validate_python("unlisted")

    def test_pagination_defaults_bounds_and_response_shape(self) -> None:
        params = PaginationParams()
        response = PaginatedResponse[str](
            items=["first"],
            page=params.page,
            page_size=params.page_size,
            total=1,
        )

        self.assertEqual(params.offset, 0)
        self.assertEqual(
            response.model_dump(),
            {"items": ["first"], "page": 1, "page_size": 20, "total": 1},
        )
        with self.assertRaises(ValidationError):
            PaginationParams(page=0)
        with self.assertRaises(ValidationError):
            PaginationParams(page_size=101)


if __name__ == "__main__":
    unittest.main()
