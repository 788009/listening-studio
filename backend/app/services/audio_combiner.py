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


class AudioCombiner:
    def combine_wav(
        self,
        segment_paths: list[Path],
        output_path: Path,
        *,
        silence_milliseconds: int,
    ) -> Path:
        if not segment_paths:
            raise ValueError("At least one audio segment is required")
        if (
            isinstance(silence_milliseconds, bool)
            or not isinstance(silence_milliseconds, int)
            or silence_milliseconds < 0
        ):
            raise ValueError("Silence duration must be a non-negative integer")
        try:
            segments = []
            for path in segment_paths:
                with path.open("rb") as input_file:
                    segments.append(AudioSegment.from_file(input_file, format="wav"))
            first = segments[0]
            normalized = [
                segment.set_frame_rate(first.frame_rate)
                .set_channels(first.channels)
                .set_sample_width(first.sample_width)
                for segment in segments
            ]
            silence = (
                AudioSegment.silent(
                    duration=silence_milliseconds,
                    frame_rate=first.frame_rate,
                )
                .set_channels(first.channels)
                .set_sample_width(first.sample_width)
            )
            combined = normalized[0]
            for segment in normalized[1:]:
                combined = combined + silence + segment
            with output_path.open("wb") as output_file:
                combined.export(output_file, format="wav")
        except Exception as exc:
            raise JobFailedError("Audio segments could not be combined") from exc
        if not output_path.is_file():
            raise JobFailedError("Audio combination produced no output file")
        return output_path
