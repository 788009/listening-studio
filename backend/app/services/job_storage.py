from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path


AUDIO_PREVIEW_JOB_TYPE = "audio_utterance_preview"


class JobStorage:
    REFERENCE_FILENAME = "reference.wav"
    AUDIO_PREVIEW_INPUT_FILENAME = "audio-preview-input.json"
    AUDIO_PREVIEW_FILENAME = "preview.wav"

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "jobs"

    def directory(self, job_id: int) -> Path:
        self._validate_id(job_id)
        return self.root / str(job_id)

    def reference_path(self, job_id: int) -> Path:
        return self.directory(job_id) / self.REFERENCE_FILENAME

    def audio_preview_input_path(self, job_id: int) -> Path:
        return self.directory(job_id) / self.AUDIO_PREVIEW_INPUT_FILENAME

    def audio_preview_path(self, job_id: int) -> Path:
        return self.directory(job_id) / self.AUDIO_PREVIEW_FILENAME

    def audio_preview_temporary_path(self, job_id: int) -> Path:
        directory = self.directory(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / ".preview.tmp.wav"

    def write_audio_preview_input(
        self,
        job_id: int,
        payload: dict[str, object],
    ) -> Path:
        directory = self.directory(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = self.audio_preview_input_path(job_id)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=directory,
            prefix=f".{self.AUDIO_PREVIEW_INPUT_FILENAME}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def read_audio_preview_input(self, job_id: int) -> dict[str, object]:
        with self.audio_preview_input_path(job_id).open(encoding="utf-8") as source:
            value = json.load(source)
        if not isinstance(value, dict):
            raise ValueError("Audio preview input must be an object")
        return value

    def finalize_audio_preview(self, job_id: int) -> Path:
        source = self.audio_preview_temporary_path(job_id)
        target = self.audio_preview_path(job_id)
        if source.is_symlink() or not source.is_file():
            raise FileNotFoundError("Temporary audio preview does not exist")
        os.replace(source, target)
        return target

    def write_reference(self, job_id: int, content: bytes) -> Path:
        directory = self.directory(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=directory,
            prefix=".reference.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            target = self.reference_path(job_id)
            os.replace(temporary, target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def cleanup(self, job_id: int) -> None:
        directory = self.directory(job_id)
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)

    @staticmethod
    def _validate_id(job_id: int) -> None:
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
            raise ValueError("Job ID must be a positive integer")
