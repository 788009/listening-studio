import os
import sys
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

import torch
import torchaudio
from vllm import ModelRegistry


ROOT_DIR = Path(__file__).resolve().parent
MATCHA_TTS_DIR = ROOT_DIR / "third_party" / "Matcha-TTS"
if str(MATCHA_TTS_DIR) not in sys.path:
    sys.path.append(str(MATCHA_TTS_DIR))

from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.vllm.cosyvoice2 import CosyVoice2ForCausalLM


MODEL_DIR = Path(
    os.environ.get(
        "COSYVOICE_MODEL_DIR",
        ROOT_DIR / "pretrained_models" / "Fun-CosyVoice3-0.5B",
    )
)
VOICE_FILE_VERSION = 1
COSYVOICE3_PROMPT = "You are a helpful assistant.<|endofprompt|>"
_MODEL = None
_MODEL_LOCK = Lock()


def _get_model():
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                ModelRegistry.register_model(
                    "CosyVoice2ForCausalLM", CosyVoice2ForCausalLM
                )
                _MODEL = AutoModel(
                    model_dir=str(MODEL_DIR),
                    load_vllm=True,
                    fp16=False,
                )
    return _MODEL


def _validate_input_file(path: str | os.PathLike[str], description: str) -> Path:
    input_path = Path(path).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"{description} does not exist: {input_path}")
    return input_path


def _prepare_output_file(path: str | os.PathLike[str]) -> Path:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def save_zero_shot_voice(
    audio_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
) -> None:
    """Extract zero-shot voice information from an audio file."""
    audio_path = _validate_input_file(audio_path, "audio file")
    output_path = _prepare_output_file(output_path)
    model = _get_model()

    voice_info = model.frontend.frontend_zero_shot(
        "", "", str(audio_path), model.sample_rate, ""
    )
    voice_info.pop("text")
    voice_info.pop("text_len")
    voice_info = {
        name: value.detach().cpu() if isinstance(value, torch.Tensor) else value
        for name, value in voice_info.items()
    }
    torch.save(
        {
            "version": VOICE_FILE_VERSION,
            "model_dir": MODEL_DIR.name,
            "voice_info": voice_info,
        },
        output_path,
    )


def _load_voice_info(voice_path: Path) -> dict[str, Any]:
    voice_file = torch.load(voice_path, map_location="cpu", weights_only=True)
    if not isinstance(voice_file, dict):
        raise ValueError(f"invalid voice file: {voice_path}")
    if voice_file.get("version") != VOICE_FILE_VERSION:
        raise ValueError(f"unsupported voice file version: {voice_path}")
    if voice_file.get("model_dir") != MODEL_DIR.name:
        raise ValueError(
            f"voice file was created for {voice_file.get('model_dir')}, "
            f"but the current model is {MODEL_DIR.name}"
        )

    voice_info = voice_file.get("voice_info")
    if not isinstance(voice_info, dict):
        raise ValueError(f"voice information is missing: {voice_path}")
    return voice_info


def generate_speech(
    voice_path: str | os.PathLike[str],
    text: str,
    output_path: str | os.PathLike[str],
) -> None:
    """Generate speech for text using a saved zero-shot voice."""
    voice_path = _validate_input_file(voice_path, "voice file")
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    output_path = _prepare_output_file(output_path)
    model = _get_model()
    voice_info = _load_voice_info(voice_path)
    voice_id = f"external_{uuid.uuid4().hex}"
    model.frontend.spk2info[voice_id] = voice_info

    speech_segments = []
    try:
        for result in model.inference_cross_lingual(
            f"{COSYVOICE3_PROMPT}{text.strip()}",
            "",
            zero_shot_spk_id=voice_id,
            stream=False,
        ):
            speech_segments.append(result["tts_speech"].detach().cpu())
    finally:
        model.frontend.spk2info.pop(voice_id, None)

    if not speech_segments:
        raise RuntimeError("speech generation returned no audio")
    torchaudio.save(
        str(output_path),
        torch.cat(speech_segments, dim=1),
        model.sample_rate,
    )
