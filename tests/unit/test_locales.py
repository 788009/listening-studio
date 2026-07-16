from __future__ import annotations

import unittest

from backend.app.core.locales import (
    match_supported_locale,
    parse_accept_language,
    resolve_locale,
)


class LocaleTest(unittest.TestCase):
    def test_matches_supported_variants(self) -> None:
        self.assertEqual(match_supported_locale("zh_cn"), "zh-CN")
        self.assertEqual(match_supported_locale("zh-Hant"), "zh-CN")
        self.assertEqual(match_supported_locale("en-US"), "en")
        self.assertIsNone(match_supported_locale("fr"))

    def test_accept_language_uses_quality_and_header_order(self) -> None:
        self.assertEqual(
            parse_accept_language("en;q=0.5, zh-CN;q=0.9"),
            "zh-CN",
        )
        self.assertEqual(parse_accept_language("zh, en"), "zh-CN")
        self.assertEqual(parse_accept_language("zh;q=0, en;q=0.5"), "en")
        self.assertIsNone(parse_accept_language("fr, de;q=0.8"))

    def test_resolution_order_and_default(self) -> None:
        self.assertEqual(
            resolve_locale(
                explicit="en-US",
                user_locale="zh-CN",
                accept_language="zh",
            ),
            "en",
        )
        self.assertEqual(
            resolve_locale(user_locale="zh-CN", accept_language="en"),
            "zh-CN",
        )
        self.assertEqual(resolve_locale(accept_language="zh"), "zh-CN")
        self.assertEqual(resolve_locale(accept_language="fr"), "en")
        with self.assertRaises(ValueError):
            resolve_locale(explicit="fr")


if __name__ == "__main__":
    unittest.main()
