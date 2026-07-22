from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Couldn't find ffmpeg or avconv.*")
    from pydub import AudioSegment

from backend.app.core.exceptions import JobFailedError


@dataclass(frozen=True)
class RenderAssemblySegment:
    audio_path: Path | None
    silence_milliseconds: int
    repeat_count: int = 1
    repeat_interval_milliseconds: int = 0


class AssemblyAudioRenderer:
    def render(
        self,
        segments: list[RenderAssemblySegment],
        output_path: Path,
    ) -> Path:
        source = next((item.audio_path for item in segments if item.audio_path), None)
        if source is None:
            raise JobFailedError("Assembly requires an audio segment")
        try:
            with source.open("rb") as input_file:
                reference = AudioSegment.from_file(input_file, format="wav")
            result = AudioSegment.empty()
            for item in segments:
                if item.audio_path is None:
                    result += self._silence(reference, item.silence_milliseconds)
                    continue
                with item.audio_path.open("rb") as input_file:
                    segment = AudioSegment.from_file(input_file, format="wav")
                segment = (
                    segment.set_frame_rate(reference.frame_rate)
                    .set_channels(reference.channels)
                    .set_sample_width(reference.sample_width)
                )
                interval = self._silence(reference, item.repeat_interval_milliseconds)
                for repeat_position in range(item.repeat_count):
                    result += segment
                    if repeat_position < item.repeat_count - 1:
                        result += interval
            with output_path.open("wb") as output_file:
                result.export(output_file, format="wav")
        except Exception as exc:
            raise JobFailedError("Assembly audio could not be rendered") from exc
        if not output_path.is_file():
            raise JobFailedError("Assembly rendering produced no output file")
        return output_path

    @staticmethod
    def _silence(reference: AudioSegment, milliseconds: int) -> AudioSegment:
        return (
            AudioSegment.silent(duration=milliseconds, frame_rate=reference.frame_rate)
            .set_channels(reference.channels)
            .set_sample_width(reference.sample_width)
        )
