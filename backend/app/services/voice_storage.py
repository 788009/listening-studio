from __future__ import annotations

import os
import shutil
import tempfile
from enum import Enum
from pathlib import Path


class VoiceAsset(str, Enum):
    MODEL = "voice.pt"
    REFERENCE = "reference.wav"


class VoiceStorage:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "voice"

    def directory(self, voice_id: int) -> Path:
        self._validate_voice_id(voice_id)
        return self.root / str(voice_id)

    def path(self, voice_id: int, asset: VoiceAsset) -> Path:
        if not isinstance(asset, VoiceAsset):
            raise ValueError("Voice asset is invalid")
        return self.directory(voice_id) / asset.value

    def prepare_directory(self, voice_id: int) -> Path:
        directory = self.directory(voice_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def create_temporary_file(self, voice_id: int, asset: VoiceAsset) -> Path:
        target = self.path(voice_id, asset)
        self.prepare_directory(voice_id)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        os.close(file_descriptor)
        return Path(temporary_name)

    def atomic_replace(
        self,
        voice_id: int,
        asset: VoiceAsset,
        temporary_path: Path,
    ) -> Path:
        target = self.path(voice_id, asset)
        candidate = Path(temporary_path)
        expected_prefix = f".{target.name}."
        if (
            candidate.parent.resolve() != target.parent.resolve()
            or not candidate.name.startswith(expected_prefix)
            or not candidate.name.endswith(".tmp")
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            raise ValueError("Temporary voice file is invalid")
        os.replace(candidate, target)
        return target

    def exists(
        self,
        voice_id: int,
        asset: VoiceAsset = VoiceAsset.MODEL,
    ) -> bool:
        path = self.path(voice_id, asset)
        return path.is_file() and not path.is_symlink()

    def discard_temporary_file(self, temporary_path: Path) -> None:
        candidate = Path(temporary_path)
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass

    def delete(self, voice_id: int) -> None:
        directory = self.directory(voice_id)
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)

    @staticmethod
    def _validate_voice_id(voice_id: int) -> None:
        if isinstance(voice_id, bool) or not isinstance(voice_id, int) or voice_id < 1:
            raise ValueError("Voice ID must be a positive integer")
