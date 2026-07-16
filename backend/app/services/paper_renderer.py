from __future__ import annotations

import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="Couldn't find ffmpeg or avconv.*",
        category=RuntimeWarning,
    )
    from pydub import AudioSegment

from backend.app.core.exceptions import JobFailedError


class PaperAudioRenderer:
    def render(
        self,
        source_paths: list[Path],
        output_path: Path,
        *,
        intro_silence_milliseconds: int,
        inter_item_silence_milliseconds: int,
        repeat_count: int,
        outro_silence_milliseconds: int,
    ) -> Path:
        if not source_paths:
            raise ValueError("Paper requires at least one source audio")
        try:
            with source_paths[0].open("rb") as source:
                first = AudioSegment.from_file(source, format="wav")
            normalized = [first]
            for path in source_paths[1:]:
                with path.open("rb") as source:
                    segment = AudioSegment.from_file(source, format="wav")
                normalized.append(
                    segment.set_frame_rate(first.frame_rate)
                    .set_channels(first.channels)
                    .set_sample_width(first.sample_width)
                )
            silence = self._silence(first, inter_item_silence_milliseconds)
            result = self._silence(first, intro_silence_milliseconds)
            for position, segment in enumerate(normalized):
                for _ in range(repeat_count):
                    result += segment
                if position < len(normalized) - 1:
                    result += silence
            result += self._silence(first, outro_silence_milliseconds)
            with output_path.open("wb") as output:
                result.export(output, format="wav")
        except Exception as exc:
            raise JobFailedError("Paper audio could not be rendered") from exc
        if not output_path.is_file():
            raise JobFailedError("Paper rendering produced no output file")
        return output_path

    @staticmethod
    def _silence(reference: AudioSegment, duration: int) -> AudioSegment:
        return (
            AudioSegment.silent(duration=duration, frame_rate=reference.frame_rate)
            .set_channels(reference.channels)
            .set_sample_width(reference.sample_width)
        )
