from __future__ import annotations

import os
import tempfile
from pathlib import Path

from backend.app.services.job_storage import JobStorage


class CorpusStorage:
    FILENAME = "corpus.txt"

    def __init__(self, data_dir: Path) -> None:
        self.job_storage = JobStorage(data_dir)

    def path(self, job_id: int) -> Path:
        return self.job_storage.directory(job_id) / self.FILENAME

    def write(self, job_id: int, corpus: str) -> Path:
        directory = self.job_storage.directory(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=directory,
            prefix=".corpus.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
                output.write(corpus)
                output.flush()
                os.fsync(output.fileno())
            target = self.path(job_id)
            os.replace(temporary, target)
            return target
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def cleanup(self, job_id: int) -> None:
        self.job_storage.cleanup(job_id)
