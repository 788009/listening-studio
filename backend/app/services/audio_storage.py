from __future__ import annotations

import os
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.exceptions import ConflictError


@dataclass(frozen=True)
class StoredAudioMetadata:
    audio_format: str
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bytes: int
    file_size_bytes: int


class AudioStorage:
    def __init__(self, data_dir: Path) -> None:
        self.audio_root = data_dir / "audio"
        self.job_root = data_dir / "jobs"

    def directory(self, audio_id: int) -> Path:
        self._validate_id(audio_id, "Audio")
        return self.audio_root / str(audio_id)

    def path(self, audio_id: int) -> Path:
        return self.directory(audio_id) / "audio.wav"

    def prepare_directory(self, audio_id: int) -> Path:
        directory = self.directory(audio_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def job_directory(self, job_id: int) -> Path:
        self._validate_id(job_id, "Job")
        return self.job_root / str(job_id)

    def prepare_job_directory(self, job_id: int) -> Path:
        directory = self.job_directory(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def temporary_audio_path(self, job_id: int) -> Path:
        return self.prepare_job_directory(job_id) / "audio.wav"

    def segment_audio_path(self, job_id: int, position: int) -> Path:
        self._validate_position(position)
        directory = self.prepare_job_directory(job_id) / "segments"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{position}.wav"

    def atomic_replace(self, audio_id: int, job_id: int) -> Path:
        source = self.temporary_audio_path(job_id)
        target = self.path(audio_id)
        if source.is_symlink() or not source.is_file():
            raise ConflictError("Temporary audio file does not exist")
        self.prepare_directory(audio_id)
        os.replace(source, target)
        return target

    def exists(self, audio_id: int) -> bool:
        path = self.path(audio_id)
        return path.is_file() and not path.is_symlink()

    def inspect(self, audio_id: int) -> StoredAudioMetadata:
        path = self.path(audio_id)
        if not self.exists(audio_id):
            raise ConflictError("Audio file does not exist")
        return self._inspect_path(path)

    def inspect_temporary(self, job_id: int) -> StoredAudioMetadata:
        path = self.temporary_audio_path(job_id)
        if path.is_symlink() or not path.is_file():
            raise ConflictError("Temporary audio file does not exist")
        return self._inspect_path(path)

    def inspect_segment(
        self,
        job_id: int,
        position: int,
    ) -> StoredAudioMetadata:
        path = self.segment_audio_path(job_id, position)
        if path.is_symlink() or not path.is_file():
            raise ConflictError("Audio segment file does not exist")
        return self._inspect_path(path)

    @staticmethod
    def _inspect_path(path: Path) -> StoredAudioMetadata:
        try:
            with wave.open(str(path), "rb") as audio_file:
                sample_rate = audio_file.getframerate()
                frame_count = audio_file.getnframes()
                channels = audio_file.getnchannels()
                sample_width_bytes = audio_file.getsampwidth()
        except (EOFError, wave.Error) as exc:
            raise ConflictError("Audio file is not a valid WAV file") from exc
        if sample_rate <= 0 or frame_count <= 0:
            raise ConflictError("Audio file contains no playable samples")
        return StoredAudioMetadata(
            audio_format="wav",
            duration_seconds=frame_count / sample_rate,
            sample_rate=sample_rate,
            channels=channels,
            sample_width_bytes=sample_width_bytes,
            file_size_bytes=path.stat().st_size,
        )

    def delete_audio(self, audio_id: int) -> None:
        self._delete_directory(self.directory(audio_id))

    def cleanup_job(self, job_id: int) -> None:
        self._delete_directory(self.job_directory(job_id))

    def stage_delete(self, audio_id: int) -> Path | None:
        directory = self.directory(audio_id)
        if not directory.exists() and not directory.is_symlink():
            return None
        staged = self.audio_root / f".deleting-{audio_id}"
        if staged.exists() or staged.is_symlink():
            raise FileExistsError("Staged audio deletion already exists")
        os.replace(directory, staged)
        return staged

    def restore_staged_delete(self, audio_id: int, staged: Path | None) -> None:
        if staged is not None and staged.exists():
            os.replace(staged, self.directory(audio_id))

    def finalize_staged_delete(self, staged: Path | None) -> None:
        if staged is not None:
            self._delete_directory(staged)

    @staticmethod
    def _delete_directory(directory: Path) -> None:
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)

    @staticmethod
    def _validate_id(value: int, resource_name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{resource_name} ID must be a positive integer")

    @staticmethod
    def _validate_position(position: int) -> None:
        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
            raise ValueError("Audio segment position must be a non-negative integer")
