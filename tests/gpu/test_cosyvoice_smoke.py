from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.integrations.cosyvoice import CosyVoiceAdapter


@unittest.skipUnless(
    os.environ.get("RUN_COSYVOICE_GPU_TESTS") == "1",
    "Set RUN_COSYVOICE_GPU_TESTS=1 to run the CosyVoice GPU smoke test",
)
class CosyVoiceGpuSmokeTest(unittest.TestCase):
    def test_extract_and_synthesize(self) -> None:
        input_path_value = os.environ.get("COSYVOICE_SMOKE_INPUT_WAV")
        if not input_path_value:
            self.fail("COSYVOICE_SMOKE_INPUT_WAV is required")
        model_dir_value = os.environ.get("COSYVOICE_MODEL_DIR")
        if not model_dir_value:
            self.fail("COSYVOICE_MODEL_DIR is required")

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            adapter = CosyVoiceAdapter(Path(model_dir_value))
            voice_path = adapter.extract_voice(
                Path(input_path_value),
                root / "voice.pt",
            )
            audio_path = adapter.synthesize(
                voice_path,
                "This is a CosyVoice GPU smoke test.",
                root / "audio.wav",
            )

            self.assertGreater(voice_path.stat().st_size, 0)
            self.assertGreater(audio_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
