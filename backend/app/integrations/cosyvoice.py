from __future__ import annotations

import importlib
import os
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Callable, Protocol

from loguru import logger

from backend.app.core.exceptions import DomainValidationError, JobFailedError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COSYVOICE_ROOT = PROJECT_ROOT / "voice" / "CosyVoice"

ExtractVoiceFunction = Callable[[Path, Path], None]
SynthesizeFunction = Callable[[Path, str, Path], None]
NormalizeAudioFunction = Callable[[Path], None]


class CosyVoiceIntegration(Protocol):
    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        pass

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        pass


@dataclass(frozen=True)
class CosyVoiceFunctions:
    extract_voice: ExtractVoiceFunction
    synthesize: SynthesizeFunction


class CosyVoiceFunctionLoader(Protocol):
    def __call__(
        self,
        cosyvoice_root: Path,
        model_dir: Path,
    ) -> CosyVoiceFunctions:
        pass


def load_cosyvoice_functions(
    cosyvoice_root: Path,
    model_dir: Path,
) -> CosyVoiceFunctions:
    project_root = cosyvoice_root.parents[1]
    for import_root in (project_root, cosyvoice_root):
        import_path = str(import_root)
        if import_path not in sys.path:
            sys.path.insert(0, import_path)
    os.environ["COSYVOICE_MODEL_DIR"] = str(model_dir)

    module = importlib.import_module("voice.CosyVoice.modules")
    return CosyVoiceFunctions(
        extract_voice=module.save_zero_shot_voice,
        synthesize=module.generate_speech,
    )


def normalize_audio_to_pcm16(audio_path: Path) -> None:
    import torchaudio

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if waveform.numel() == 0 or sample_rate <= 0:
        raise ValueError("CosyVoice generated empty audio")
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=audio_path.parent,
        prefix=f".{audio_path.stem}.",
        suffix=".wav",
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        torchaudio.save(
            str(temporary_path),
            waveform,
            sample_rate,
            encoding="PCM_S",
            bits_per_sample=16,
        )
        os.replace(temporary_path, audio_path)
    finally:
        temporary_path.unlink(missing_ok=True)


class CosyVoiceAdapter:
    def __init__(
        self,
        model_dir: Path,
        *,
        vllm_enabled: bool = True,
        vllm_gpu_memory_utilization: float = 0.2,
        vllm_max_num_seqs: int = 4,
        cosyvoice_root: Path = DEFAULT_COSYVOICE_ROOT,
        function_loader: CosyVoiceFunctionLoader = load_cosyvoice_functions,
        audio_normalizer: NormalizeAudioFunction = normalize_audio_to_pcm16,
    ) -> None:
        if not isinstance(vllm_enabled, bool):
            raise ValueError("vLLM enabled flag must be a boolean")
        if (
            isinstance(vllm_gpu_memory_utilization, bool)
            or not isinstance(vllm_gpu_memory_utilization, (int, float))
            or not 0 < vllm_gpu_memory_utilization <= 0.9
        ):
            raise ValueError(
                "vLLM GPU memory utilization must be greater than 0 and at most 0.9"
            )
        if (
            isinstance(vllm_max_num_seqs, bool)
            or not isinstance(vllm_max_num_seqs, int)
            or not 1 <= vllm_max_num_seqs <= 16
        ):
            raise ValueError("vLLM maximum sequence count must be between 1 and 16")
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.cosyvoice_root = Path(cosyvoice_root).expanduser().resolve()
        self.vllm_enabled = vllm_enabled
        self.vllm_gpu_memory_utilization = float(vllm_gpu_memory_utilization)
        self.vllm_max_num_seqs = vllm_max_num_seqs
        self.function_loader = function_loader
        self.audio_normalizer = audio_normalizer
        self._functions: CosyVoiceFunctions | None = None
        self._load_lock = Lock()

    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        source = self._validate_input_file(input_audio_path, "inputAudioPath")
        output = self._validate_output_file(output_voice_path, "outputVoicePath")
        functions = self._get_functions()
        logger.info("CosyVoice extraction started")
        try:
            functions.extract_voice(source, output)
        except Exception as exc:
            logger.exception("CosyVoice extraction failed")
            raise JobFailedError(
                "Voice extraction failed",
                details={"exceptionType": type(exc).__name__},
            ) from exc
        self._require_output(output, "Voice extraction")
        logger.info("CosyVoice extraction completed")
        return output

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        source = self._validate_input_file(voice_path, "voicePath")
        normalized_text = self._validate_text(text)
        output = self._validate_output_file(output_audio_path, "outputAudioPath")
        functions = self._get_functions()
        logger.info("CosyVoice synthesis started text_length={}", len(normalized_text))
        try:
            functions.synthesize(source, normalized_text, output)
            self.audio_normalizer(output)
        except Exception as exc:
            logger.exception("CosyVoice synthesis failed")
            raise JobFailedError(
                "Speech synthesis failed",
                details={"exceptionType": type(exc).__name__},
            ) from exc
        self._require_output(output, "Speech synthesis")
        logger.info("CosyVoice synthesis completed")
        return output

    def _get_functions(self) -> CosyVoiceFunctions:
        self._validate_runtime()
        if self._functions is None:
            with self._load_lock:
                if self._functions is None:
                    try:
                        os.environ["COSYVOICE_VLLM_ENABLED"] = (
                            "true" if self.vllm_enabled else "false"
                        )
                        os.environ["COSYVOICE_VLLM_GPU_MEMORY_UTILIZATION"] = str(
                            self.vllm_gpu_memory_utilization
                        )
                        os.environ["COSYVOICE_VLLM_MAX_NUM_SEQS"] = str(
                            self.vllm_max_num_seqs
                        )
                        logger.info(
                            "CosyVoice loading vllm_enabled={} "
                            "vllm_gpu_memory_utilization={} vllm_max_num_seqs={}",
                            self.vllm_enabled,
                            self.vllm_gpu_memory_utilization,
                            self.vllm_max_num_seqs,
                        )
                        self._functions = self.function_loader(
                            self.cosyvoice_root,
                            self.model_dir,
                        )
                    except Exception as exc:
                        logger.exception("CosyVoice integration could not be loaded")
                        raise JobFailedError(
                            "CosyVoice integration is unavailable",
                            details={"exceptionType": type(exc).__name__},
                        ) from exc
        return self._functions

    def _validate_runtime(self) -> None:
        if not self.model_dir.is_dir():
            raise JobFailedError("CosyVoice model directory is unavailable")
        modules_path = self.cosyvoice_root / "modules.py"
        if not modules_path.is_file():
            raise JobFailedError("CosyVoice integration module is unavailable")

    @staticmethod
    def _validate_input_file(path: Path, field_name: str) -> Path:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            raise DomainValidationError(
                "CosyVoice input file does not exist",
                details={"field": field_name},
            )
        return candidate

    @staticmethod
    def _validate_output_file(path: Path, field_name: str) -> Path:
        candidate = Path(path).expanduser().resolve()
        if not candidate.parent.is_dir():
            raise DomainValidationError(
                "CosyVoice output directory does not exist",
                details={"field": field_name},
            )
        if candidate.exists() and not candidate.is_file():
            raise DomainValidationError(
                "CosyVoice output path is not a file",
                details={"field": field_name},
            )
        return candidate

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise DomainValidationError(
                "Synthesis text cannot be empty",
                details={"field": "text"},
            )
        return text.strip()

    @staticmethod
    def _require_output(output_path: Path, operation: str) -> None:
        if not output_path.is_file():
            raise JobFailedError(f"{operation} produced no output file")


@dataclass(frozen=True)
class FakeCosyVoiceCall:
    operation: str
    input_path: Path
    output_path: Path
    text: str | None = None


@dataclass
class FakeCosyVoiceIntegration:
    failure: Exception | None = None
    calls: list[FakeCosyVoiceCall] = field(default_factory=list)

    def extract_voice(self, input_audio_path: Path, output_voice_path: Path) -> Path:
        self._raise_failure()
        source = Path(input_audio_path)
        output = Path(output_voice_path)
        self.calls.append(FakeCosyVoiceCall("extract_voice", source, output))
        output.write_bytes(b"fake-cosyvoice-model")
        return output

    def synthesize(
        self,
        voice_path: Path,
        text: str,
        output_audio_path: Path,
    ) -> Path:
        self._raise_failure()
        source = Path(voice_path)
        output = Path(output_audio_path)
        self.calls.append(FakeCosyVoiceCall("synthesize", source, output, text))
        with wave.open(str(output), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\x00\x00" * 800)
        return output

    def _raise_failure(self) -> None:
        if self.failure is not None:
            raise self.failure
