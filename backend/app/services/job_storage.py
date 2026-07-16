from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class JobStorage:
    REFERENCE_FILENAME = "reference.wav"

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "jobs"

    def directory(self, job_id: int) -> Path:
        self._validate_id(job_id)
        return self.root / str(job_id)

    def reference_path(self, job_id: int) -> Path:
        return self.directory(job_id) / self.REFERENCE_FILENAME

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
