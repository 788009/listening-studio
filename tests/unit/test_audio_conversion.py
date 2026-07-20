from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg

from backend.app.integrations.audio_conversion import (
    AudioConversionError,
    FfmpegAudioTranscoder,
)


class AudioConversionTest(unittest.TestCase):
    @staticmethod
    def wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio_file:
            audio_file.setnchannels(2)
            audio_file.setsampwidth(2)
            audio_file.setframerate(sample_rate)
            audio_file.writeframes(
                b"\x00\x00\x00\x00" * int(duration_seconds * sample_rate)
            )
        return output.getvalue()

    def test_converts_mp3_to_normalized_wav(self) -> None:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            source = directory / "source.wav"
            encoded = directory / "encoded.mp3"
            source.write_bytes(self.wav_bytes(2.0))
            subprocess.run(
                [
                    executable,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    str(source),
                    str(encoded),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            converted = FfmpegAudioTranscoder().convert_to_wav(
                encoded.read_bytes(),
                extension=".mp3",
                max_duration_seconds=30.0,
            )

        with wave.open(io.BytesIO(converted), "rb") as audio_file:
            self.assertEqual(audio_file.getnchannels(), 1)
            self.assertEqual(audio_file.getsampwidth(), 2)
            self.assertEqual(audio_file.getframerate(), 16000)
            self.assertAlmostEqual(
                audio_file.getnframes() / audio_file.getframerate(),
                2.0,
                places=1,
            )

    def test_rejects_undecodable_input(self) -> None:
        with self.assertRaises(AudioConversionError):
            FfmpegAudioTranscoder().convert_to_wav(
                b"not audio",
                extension=".mp3",
                max_duration_seconds=30.0,
            )


if __name__ == "__main__":
    unittest.main()
