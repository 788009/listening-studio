from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import imageio_ffmpeg


class AudioConversionError(RuntimeError):
    pass


class FfmpegAudioTranscoder:
    def __init__(
        self,
        *,
        executable_provider: Callable[[], str] = imageio_ffmpeg.get_ffmpeg_exe,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Audio conversion timeout must be positive")
        self.executable_provider = executable_provider
        self.timeout_seconds = timeout_seconds

    def convert_to_wav(
        self,
        content: bytes,
        *,
        extension: str,
        max_duration_seconds: float,
    ) -> bytes:
        if not isinstance(content, bytes) or not content:
            raise AudioConversionError("Audio input is empty")
        if not extension.startswith(".") or "/" in extension or "\\" in extension:
            raise AudioConversionError("Audio extension is invalid")
        try:
            executable = self.executable_provider()
        except Exception as exc:
            raise AudioConversionError("FFmpeg is unavailable") from exc

        with tempfile.TemporaryDirectory(prefix="listening-audio-") as temporary_dir:
            directory = Path(temporary_dir)
            input_path = directory / f"input{extension}"
            output_path = directory / "output.wav"
            input_path.write_bytes(content)
            command = [
                executable,
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(input_path),
                "-t",
                f"{max_duration_seconds + 1:g}",
                "-map_metadata",
                "-1",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=self.timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise AudioConversionError("Audio conversion failed") from exc
            if completed.returncode != 0 or not output_path.is_file():
                raise AudioConversionError("Audio conversion failed")
            try:
                return output_path.read_bytes()
            except OSError as exc:
                raise AudioConversionError("Converted audio could not be read") from exc
