from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from backend.app.core.exceptions import DomainValidationError
from backend.app.integrations.cosyvoice import FakeCosyVoiceIntegration
from backend.app.services.speech_synthesis import (
    ChunkedSpeechSynthesizer,
    chunk_synthesis_text,
)


class SpeechSynthesisTest(unittest.TestCase):
    @staticmethod
    def sentence(prefix: str, word_count: int) -> str:
        return " ".join([prefix, *[f"word{index}" for index in range(2, word_count + 1)]]) + "."

    def test_groups_the_longest_complete_sentences_up_to_thirty_words(self) -> None:
        first = self.sentence("First", 8)
        second = self.sentence("Second", 12)
        third = self.sentence("Third", 11)
        fourth = self.sentence("Fourth", 19)

        self.assertEqual(
            chunk_synthesis_text(" ".join([first, second, third, fourth])),
            [f"{first} {second}", f"{third} {fourth}"],
        )

    def test_sentence_with_at_least_thirty_words_is_its_own_chunk(self) -> None:
        thirty = self.sentence("Thirty", 30)
        short = self.sentence("Short", 2)
        thirty_one = self.sentence("Long", 31)

        self.assertEqual(
            chunk_synthesis_text(" ".join([thirty, short, thirty_one, short])),
            [thirty, short, thirty_one, short],
        )

    def test_preserves_sentence_punctuation_and_handles_abbreviations(self) -> None:
        text = 'Dr. Smith asked, "Are you ready?" She said yes! Final words'

        self.assertEqual(chunk_synthesis_text(text, max_words=6), [
            'Dr. Smith asked, "Are you ready?"',
            "She said yes! Final words",
        ])

    def test_rejects_empty_text_and_invalid_limit(self) -> None:
        with self.assertRaises(DomainValidationError):
            chunk_synthesis_text("   ")
        with self.assertRaises(ValueError):
            chunk_synthesis_text("Text.", max_words=0)

    def test_synthesizes_each_chunk_and_concatenates_without_silence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            voice_path = root / "voice.pt"
            voice_path.write_bytes(b"voice")
            output_path = root / "audio.wav"
            first = self.sentence("First", 20)
            second = self.sentence("Second", 20)
            integration = FakeCosyVoiceIntegration()

            result = ChunkedSpeechSynthesizer(integration).synthesize(
                voice_path,
                f"{first} {second}",
                output_path,
            )

            self.assertEqual(result, output_path)
            self.assertEqual(
                [call.text for call in integration.calls],
                [first, second],
            )
            with wave.open(str(output_path), "rb") as audio_file:
                self.assertEqual(audio_file.getnframes(), 1600)
                self.assertEqual(audio_file.getframerate(), 8000)


if __name__ == "__main__":
    unittest.main()
