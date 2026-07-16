from __future__ import annotations

import unittest
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.integrations.identity import (
    ExternalIdentity,
    PlaceholderIdentityProvider,
)


class PlaceholderIdentityProviderTest(unittest.TestCase):
    @staticmethod
    def provider() -> PlaceholderIdentityProvider:
        settings = Settings(
            _env_file=None,
            debug_auth_enabled=True,
            auth_session_secret="test-session-secret-with-32-characters",
            auth_session_max_age_seconds=60,
            cosyvoice_model_dir=Path("/models/cosyvoice"),
        )
        return PlaceholderIdentityProvider(settings)

    def test_signed_session_round_trip(self) -> None:
        provider = self.provider()
        identity = ExternalIdentity("https://issuer.example", "teacher-1")

        token = provider.issue_session(identity, now=100)

        self.assertEqual(provider.verify_session(token, now=159), identity)
        self.assertIsNone(provider.verify_session(token, now=160))

    def test_tampered_session_is_rejected(self) -> None:
        provider = self.provider()
        token = provider.issue_session(
            ExternalIdentity("https://issuer.example", "teacher-1"),
            now=100,
        )
        payload, signature = token.split(".", maxsplit=1)
        tampered_token = f"{payload[:-1]}A.{signature}"

        self.assertIsNone(provider.verify_session(tampered_token, now=101))
        self.assertIsNone(provider.verify_session("invalid", now=101))


if __name__ == "__main__":
    unittest.main()
