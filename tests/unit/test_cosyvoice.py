from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core.exceptions import DomainValidationError, JobFailedError
from backend.app.integrations.cosyvoice import (
    CosyVoiceAdapter,
    CosyVoiceFunctions,
    FakeCosyVoiceIntegration,
    load_cosyvoice_functions,
)


class CosyVoiceIntegrationTest(unittest.TestCase):
    def test_module_import_is_lazy(self) -> None:
        importlib.import_module("backend.app.integrations.cosyvoice")

        self.assertNotIn("voice.CosyVoice.modules", sys.modules)

    def test_fake_records_parameters_and_writes_expected_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            input_audio = root / "reference.wav"
            input_audio.write_bytes(b"reference")
            voice_path = root / "voice.pt"
            audio_path = root / "audio.wav"
            fake = FakeCosyVoiceIntegration()

            extracted = fake.extract_voice(input_audio, voice_path)
            synthesized = fake.synthesize(voice_path, "Test text", audio_path)

            self.assertEqual(extracted, voice_path)
            self.assertEqual(synthesized, audio_path)
            self.assertTrue(voice_path.is_file())
            with wave.open(str(audio_path), "rb") as audio_file:
                self.assertEqual(audio_file.getframerate(), 8000)
                self.assertEqual(audio_file.getnchannels(), 1)
            self.assertEqual(fake.calls[0].operation, "extract_voice")
            self.assertEqual(fake.calls[0].input_path, input_audio)
            self.assertEqual(fake.calls[0].output_path, voice_path)
            self.assertEqual(fake.calls[1].operation, "synthesize")
            self.assertEqual(fake.calls[1].text, "Test text")

    def test_adapter_validates_and_forwards_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            model_dir = root / "model"
            cosyvoice_root = root / "voice" / "CosyVoice"
            output_dir = root / "output"
            model_dir.mkdir()
            cosyvoice_root.mkdir(parents=True)
            output_dir.mkdir()
            (cosyvoice_root / "modules.py").write_text("", encoding="utf-8")
            reference = root / "reference.wav"
            reference.write_bytes(b"reference")
            voice_output = output_dir / "voice.pt"
            audio_output = output_dir / "audio.wav"
            loader_calls: list[tuple[Path, Path]] = []
            function_calls: list[tuple[object, ...]] = []

            def extract(source: Path, output: Path) -> None:
                function_calls.append(("extract", source, output))
                output.write_bytes(b"voice")

            def synthesize(source: Path, text: str, output: Path) -> None:
                function_calls.append(("synthesize", source, text, output))
                output.write_bytes(b"audio")

            def loader(cosy_root: Path, model: Path) -> CosyVoiceFunctions:
                loader_calls.append((cosy_root, model))
                return CosyVoiceFunctions(extract, synthesize)

            adapter = CosyVoiceAdapter(
                model_dir,
                cosyvoice_root=cosyvoice_root,
                function_loader=loader,
            )
            adapter.extract_voice(reference, voice_output)
            adapter.synthesize(voice_output, "  Test text  ", audio_output)

            self.assertEqual(loader_calls, [(cosyvoice_root, model_dir)])
            self.assertEqual(
                function_calls,
                [
                    ("extract", reference.resolve(), voice_output.resolve()),
                    (
                        "synthesize",
                        voice_output.resolve(),
                        "Test text",
                        audio_output.resolve(),
                    ),
                ],
            )

    def test_adapter_rejects_invalid_paths_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            model_dir = root / "model"
            cosyvoice_root = root / "voice" / "CosyVoice"
            model_dir.mkdir()
            cosyvoice_root.mkdir(parents=True)
            (cosyvoice_root / "modules.py").write_text("", encoding="utf-8")
            source = root / "source.wav"
            source.write_bytes(b"source")
            output = root / "output.pt"
            functions = CosyVoiceFunctions(
                lambda source, target: target.write_bytes(b"voice"),
                lambda source, text, target: target.write_bytes(b"audio"),
            )
            adapter = CosyVoiceAdapter(
                model_dir,
                cosyvoice_root=cosyvoice_root,
                function_loader=lambda root, model: functions,
            )

            with self.assertRaises(DomainValidationError):
                adapter.extract_voice(root / "missing.wav", output)
            with self.assertRaises(DomainValidationError):
                adapter.extract_voice(source, root / "missing" / "voice.pt")
            with self.assertRaises(DomainValidationError):
                adapter.synthesize(source, "   ", root / "audio.wav")

            unavailable = CosyVoiceAdapter(
                root / "missing-model",
                cosyvoice_root=cosyvoice_root,
                function_loader=lambda root, model: functions,
            )
            with self.assertRaises(JobFailedError):
                unavailable.extract_voice(source, output)

    def test_adapter_maps_loader_and_model_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            model_dir = root / "model"
            cosyvoice_root = root / "voice" / "CosyVoice"
            model_dir.mkdir()
            cosyvoice_root.mkdir(parents=True)
            (cosyvoice_root / "modules.py").write_text("", encoding="utf-8")
            source = root / "source.wav"
            source.write_bytes(b"source")

            def failing_loader(root: Path, model: Path) -> CosyVoiceFunctions:
                raise ImportError("missing dependency")

            loading_adapter = CosyVoiceAdapter(
                model_dir,
                cosyvoice_root=cosyvoice_root,
                function_loader=failing_loader,
            )
            with self.assertRaises(JobFailedError) as loading_error:
                loading_adapter.extract_voice(source, root / "voice.pt")
            self.assertEqual(
                loading_error.exception.details,
                {"exceptionType": "ImportError"},
            )

            def fail_extract(source: Path, output: Path) -> None:
                raise RuntimeError("model failed")

            model_adapter = CosyVoiceAdapter(
                model_dir,
                cosyvoice_root=cosyvoice_root,
                function_loader=lambda root, model: CosyVoiceFunctions(
                    fail_extract,
                    lambda source, text, output: None,
                ),
            )
            with self.assertRaises(JobFailedError) as model_error:
                model_adapter.extract_voice(source, root / "voice.pt")
            self.assertEqual(
                model_error.exception.details,
                {"exceptionType": "RuntimeError"},
            )

    def test_loader_configures_local_import_paths_and_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_root = Path(temporary_dir)
            cosyvoice_root = project_root / "voice" / "CosyVoice"
            model_dir = project_root / "model"
            cosyvoice_root.mkdir(parents=True)
            model_dir.mkdir()
            extract = lambda source, output: None
            synthesize = lambda source, text, output: None
            module = SimpleNamespace(
                save_zero_shot_voice=extract,
                generate_speech=synthesize,
            )

            with (
                patch.object(sys, "path", list(sys.path)),
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "backend.app.integrations.cosyvoice.importlib.import_module",
                    return_value=module,
                ) as import_module,
            ):
                functions = load_cosyvoice_functions(cosyvoice_root, model_dir)

                import_module.assert_called_once_with("voice.CosyVoice.modules")
                self.assertIn(str(project_root), sys.path)
                self.assertIn(str(cosyvoice_root), sys.path)
                self.assertEqual(os.environ["COSYVOICE_MODEL_DIR"], str(model_dir))
                self.assertIs(functions.extract_voice, extract)
                self.assertIs(functions.synthesize, synthesize)


if __name__ == "__main__":
    unittest.main()
