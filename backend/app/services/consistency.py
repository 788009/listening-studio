from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError
from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.generation_batch import GenerationBatchItem
from backend.app.db.models.job import Job, JobStatus
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)
from backend.app.services.audio_storage import AudioStorage, StoredAudioMetadata
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage


_STAGED_DELETE_PATTERN = re.compile(r"^\.deleting-([1-9][0-9]*)$")
_VOICE_TEMPORARY_PATTERN = re.compile(
    r"^\.(?:voice\.pt|reference\.wav)\..+\.tmp$"
)
_INTERRUPTED_JOB_ERROR = "Worker stopped before the task completed"
_MISSING_RESOURCE_ERROR = "Consistency repair: required file is unavailable"


@dataclass
class ConsistencyIssue:
    code: str
    resource_type: str
    resource_id: int | None
    message: str
    paths: list[str]
    original_status: str | None = None
    target_status: str | None = None
    action: str = "none"
    target_path: str | None = None
    result: str = "reported"
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ConsistencyReport:
    mode: str
    issues: list[ConsistencyIssue]

    def to_dict(self) -> dict[str, object]:
        counts = {
            result: sum(issue.result == result for issue in self.issues)
            for result in ("reported", "repaired", "skipped", "failed")
        }
        return {
            "mode": self.mode,
            "summary": {"issues": len(self.issues), **counts},
            "issues": [issue.to_dict() for issue in self.issues],
        }


def interrupted_job_target(job: Job) -> JobStatus | None:
    if job.status is JobStatus.QUEUED and job.cancel_requested:
        return JobStatus.CANCELLED
    if job.status is not JobStatus.RUNNING:
        return None
    if job.cancel_requested:
        return JobStatus.CANCELLED
    if job.retryable:
        return JobStatus.QUEUED
    return JobStatus.FAILED


def recover_interrupted_job(job: Job, target: JobStatus) -> None:
    now = datetime.now(timezone.utc)
    job.status = target
    if target is JobStatus.QUEUED:
        job.progress = 0
        job.claimed_at = None
        job.started_at = None
        job.finished_at = None
        job.error_summary = None
    elif target is JobStatus.CANCELLED:
        job.cancel_requested = True
        job.finished_at = now
    else:
        job.error_summary = _INTERRUPTED_JOB_ERROR
        job.finished_at = now


class ConsistencyService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.voice_storage = VoiceStorage(self.data_dir)
        self.audio_storage = AudioStorage(self.data_dir)

    def run(self, session: Session, *, apply: bool = False) -> ConsistencyReport:
        issues = self.scan(session)
        if apply:
            for issue in issues:
                self._apply_issue(session, issue)
        return ConsistencyReport(mode="apply" if apply else "dry-run", issues=issues)

    def scan(self, session: Session) -> list[ConsistencyIssue]:
        voices = list(session.scalars(select(Voice).order_by(Voice.id)))
        audios = list(session.scalars(select(Audio).order_by(Audio.id)))
        jobs = list(session.scalars(select(Job).order_by(Job.id)))
        active_voice_ids, active_audio_ids = self._active_resource_ids(session, jobs)

        issues: list[ConsistencyIssue] = []
        for voice in voices:
            issues.extend(self._scan_voice(voice, active_voice_ids))
        for audio in audios:
            issues.extend(self._scan_audio(audio, active_audio_ids))
        for job in jobs:
            issues.extend(self._scan_job(job))

        issues.extend(
            self._scan_resource_root(
                self.voice_storage.root,
                {voice.id for voice in voices},
                "voice",
            )
        )
        issues.extend(
            self._scan_resource_root(
                self.audio_storage.audio_root,
                {audio.id for audio in audios},
                "audio",
            )
        )
        issues.extend(self._scan_job_root({job.id: job for job in jobs}))
        issues.extend(self._scan_voice_temporary_files({voice.id for voice in voices}))
        issues.extend(self._scan_audio_unknown_files({audio.id for audio in audios}))
        return issues

    def _scan_voice(
        self,
        voice: Voice,
        active_voice_ids: set[int],
    ) -> list[ConsistencyIssue]:
        required = [self.voice_storage.path(voice.id, VoiceAsset.MODEL)]
        if voice.sample_source is VoiceSampleSource.ORIGINAL:
            required.append(self.voice_storage.path(voice.id, VoiceAsset.REFERENCE))
        missing = [path for path in required if not self._regular_file(path)]
        if voice.status is VoiceStatus.READY and missing:
            return [
                ConsistencyIssue(
                    code="missing_file",
                    resource_type="voice",
                    resource_id=voice.id,
                    message="Ready voice is missing required files",
                    paths=[str(path) for path in missing],
                    original_status=voice.status.value,
                    target_status=VoiceStatus.FAILED.value,
                    action="mark_voice_failed",
                )
            ]
        if (
            voice.status is VoiceStatus.PROCESSING
            and voice.id not in active_voice_ids
        ):
            return [
                ConsistencyIssue(
                    code="status_mismatch",
                    resource_type="voice",
                    resource_id=voice.id,
                    message="Processing voice has no active task",
                    paths=[str(self.voice_storage.directory(voice.id))],
                    original_status=voice.status.value,
                    target_status=VoiceStatus.FAILED.value,
                    action="mark_voice_failed",
                )
            ]
        if voice.status is not VoiceStatus.READY and voice.visibility is VoiceVisibility.PUBLIC:
            return [
                ConsistencyIssue(
                    code="status_mismatch",
                    resource_type="voice",
                    resource_id=voice.id,
                    message="Non-ready voice is public",
                    paths=[str(self.voice_storage.directory(voice.id))],
                    original_status=voice.status.value,
                    target_status=voice.status.value,
                    action="make_voice_private",
                )
            ]
        return []

    def _scan_audio(
        self,
        audio: Audio,
        active_audio_ids: set[int],
    ) -> list[ConsistencyIssue]:
        path = self.audio_storage.path(audio.id)
        if audio.status is AudioStatus.READY:
            if not self._regular_file(path):
                return [
                    ConsistencyIssue(
                        code="missing_file",
                        resource_type="audio",
                        resource_id=audio.id,
                        message="Ready audio is missing its WAV file",
                        paths=[str(path)],
                        original_status=audio.status.value,
                        target_status=AudioStatus.FAILED.value,
                        action="mark_audio_failed",
                    )
                ]
            try:
                metadata = self.audio_storage.inspect(audio.id)
            except ConflictError:
                return [
                    ConsistencyIssue(
                        code="invalid_file",
                        resource_type="audio",
                        resource_id=audio.id,
                        message="Ready audio file is not a playable WAV file",
                        paths=[str(path)],
                        original_status=audio.status.value,
                        target_status=AudioStatus.FAILED.value,
                        action="mark_audio_failed",
                    )
                ]
            if not self._audio_metadata_matches(audio, metadata):
                return [
                    ConsistencyIssue(
                        code="status_mismatch",
                        resource_type="audio",
                        resource_id=audio.id,
                        message="Stored audio metadata does not match its WAV file",
                        paths=[str(path)],
                        original_status=audio.status.value,
                        target_status=audio.status.value,
                        action="refresh_audio_metadata",
                    )
                ]
        elif audio.status is AudioStatus.PROCESSING and audio.id not in active_audio_ids:
            return [
                ConsistencyIssue(
                    code="status_mismatch",
                    resource_type="audio",
                    resource_id=audio.id,
                    message="Processing audio has no active task",
                    paths=[str(path)],
                    original_status=audio.status.value,
                    target_status=AudioStatus.FAILED.value,
                    action="mark_audio_failed",
                )
            ]
        elif audio.visibility is AudioVisibility.PUBLIC:
            return [
                ConsistencyIssue(
                    code="status_mismatch",
                    resource_type="audio",
                    resource_id=audio.id,
                    message="Non-ready audio is public",
                    paths=[str(path)],
                    original_status=audio.status.value,
                    target_status=audio.status.value,
                    action="make_audio_private",
                )
            ]
        return []

    def _scan_job(self, job: Job) -> list[ConsistencyIssue]:
        target = interrupted_job_target(job)
        if target is None:
            return []
        return [
            ConsistencyIssue(
                code="dangling_job",
                resource_type="job",
                resource_id=job.id,
                message="Task was interrupted before reaching a terminal state",
                paths=[str(self.audio_storage.job_directory(job.id))],
                original_status=job.status.value,
                target_status=target.value,
                action="recover_job",
            )
        ]

    def _scan_resource_root(
        self,
        root: Path,
        known_ids: set[int],
        resource_type: str,
    ) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        for entry in self._entries(root):
            if entry.name.isdigit() and int(entry.name) > 0:
                resource_id = int(entry.name)
                if resource_id not in known_ids or entry.is_symlink() or not entry.is_dir():
                    issues.append(self._orphan_issue(resource_type, resource_id, entry))
                continue
            staged = _STAGED_DELETE_PATTERN.fullmatch(entry.name)
            if staged:
                resource_id = int(staged.group(1))
                canonical = root / str(resource_id)
                if resource_id not in known_ids:
                    action = "remove_known_directory"
                    target_path = None
                elif not canonical.exists() and not canonical.is_symlink():
                    action = "restore_staged_delete"
                    target_path = str(canonical)
                else:
                    action = "none"
                    target_path = None
                issues.append(
                    ConsistencyIssue(
                        code="legacy_temporary",
                        resource_type=resource_type,
                        resource_id=resource_id,
                        message="Staged deletion was not finalized",
                        paths=[str(entry)],
                        action=action,
                        target_path=target_path,
                    )
                )
                continue
            issues.append(self._orphan_issue(resource_type, None, entry))
        return issues

    def _scan_job_root(self, jobs: dict[int, Job]) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        for entry in self._entries(self.audio_storage.job_root):
            if entry.name.isdigit() and int(entry.name) > 0:
                job_id = int(entry.name)
                job = jobs.get(job_id)
                if job is None or entry.is_symlink() or not entry.is_dir():
                    issues.append(self._orphan_issue("job", job_id, entry))
                elif job.status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                }:
                    issues.append(
                        ConsistencyIssue(
                            code="legacy_temporary",
                            resource_type="job",
                            resource_id=job_id,
                            message="Terminal task still has temporary files",
                            paths=[str(entry)],
                            original_status=job.status.value,
                            target_status=job.status.value,
                            action="remove_known_directory",
                        )
                    )
                continue
            issues.append(self._orphan_issue("job", None, entry))
        return issues

    def _scan_voice_temporary_files(self, known_ids: set[int]) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        for voice_id in sorted(known_ids):
            directory = self.voice_storage.directory(voice_id)
            for entry in self._entries(directory):
                if (
                    _VOICE_TEMPORARY_PATTERN.fullmatch(entry.name)
                    and entry.is_file()
                    and not entry.is_symlink()
                ):
                    issues.append(
                        ConsistencyIssue(
                            code="legacy_temporary",
                            resource_type="voice",
                            resource_id=voice_id,
                            message="Voice has a recognized temporary file",
                            paths=[str(entry)],
                            action="remove_known_file",
                        )
                    )
                elif entry.name not in {asset.value for asset in VoiceAsset}:
                    issues.append(self._unknown_file_issue("voice", voice_id, entry))
        return issues

    def _scan_audio_unknown_files(self, known_ids: set[int]) -> list[ConsistencyIssue]:
        issues: list[ConsistencyIssue] = []
        for audio_id in sorted(known_ids):
            directory = self.audio_storage.directory(audio_id)
            for entry in self._entries(directory):
                if entry.name != "audio.wav":
                    issues.append(self._unknown_file_issue("audio", audio_id, entry))
        return issues

    def _apply_issue(self, session: Session, issue: ConsistencyIssue) -> None:
        if issue.action == "none":
            issue.result = "skipped"
            self._log_repair(issue)
            return
        try:
            changed = self._execute_action(session, issue)
        except Exception as exc:
            session.rollback()
            issue.result = "failed"
            issue.error = type(exc).__name__
            self._log_repair(issue)
            return
        issue.result = "repaired" if changed else "skipped"
        self._log_repair(issue)

    def _execute_action(self, session: Session, issue: ConsistencyIssue) -> bool:
        resource_id = issue.resource_id
        if issue.action in {"mark_voice_failed", "make_voice_private"}:
            assert resource_id is not None
            voice = session.get(Voice, resource_id)
            if voice is None:
                return False
            if issue.action == "mark_voice_failed":
                if voice.status.value != issue.original_status:
                    return False
                voice.status = VoiceStatus.FAILED
                voice.visibility = VoiceVisibility.PRIVATE
                voice.error_summary = _MISSING_RESOURCE_ERROR
            elif voice.visibility is VoiceVisibility.PRIVATE:
                return False
            else:
                voice.visibility = VoiceVisibility.PRIVATE
            session.commit()
            return True
        if issue.action in {
            "mark_audio_failed",
            "make_audio_private",
            "refresh_audio_metadata",
        }:
            assert resource_id is not None
            audio = session.get(Audio, resource_id)
            if audio is None:
                return False
            if issue.action == "mark_audio_failed":
                if audio.status.value != issue.original_status:
                    return False
                audio.status = AudioStatus.FAILED
                audio.visibility = AudioVisibility.PRIVATE
                audio.audio_format = None
                audio.duration_seconds = None
                audio.sample_rate = None
                audio.channels = None
                audio.sample_width_bytes = None
                audio.file_size_bytes = None
                audio.error_summary = _MISSING_RESOURCE_ERROR
            elif issue.action == "make_audio_private":
                if audio.visibility is AudioVisibility.PRIVATE:
                    return False
                audio.visibility = AudioVisibility.PRIVATE
            else:
                metadata = self.audio_storage.inspect(resource_id)
                self._set_audio_metadata(audio, metadata)
            session.commit()
            return True
        if issue.action == "recover_job":
            assert resource_id is not None
            job = session.get(Job, resource_id)
            if job is None:
                return False
            target = interrupted_job_target(job)
            if target is None or target.value != issue.target_status:
                return False
            recover_interrupted_job(job, target)
            session.commit()
            if target in {JobStatus.FAILED, JobStatus.CANCELLED}:
                try:
                    self._remove_path(Path(issue.paths[0]))
                except OSError as exc:
                    issue.error = f"temporary_cleanup:{type(exc).__name__}"
            return True
        if issue.action == "remove_known_file":
            path = Path(issue.paths[0])
            if path.is_symlink() or not path.is_file():
                return False
            path.unlink()
            return True
        if issue.action == "remove_known_directory":
            return self._remove_path(Path(issue.paths[0]))
        if issue.action == "restore_staged_delete":
            source = Path(issue.paths[0])
            assert issue.target_path is not None
            target = Path(issue.target_path)
            if (
                source.is_symlink()
                or not source.is_dir()
                or target.exists()
                or target.is_symlink()
            ):
                return False
            os.replace(source, target)
            return True
        raise RuntimeError("Unknown consistency repair action")

    @staticmethod
    def _active_resource_ids(
        session: Session,
        jobs: list[Job],
    ) -> tuple[set[int], set[int]]:
        voice_ids: set[int] = set()
        audio_ids: set[int] = set()
        batch_ids: set[int] = set()
        item_ids: set[int] = set()
        for job in jobs:
            if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                continue
            for key, destination in (
                ("voiceId", voice_ids),
                ("audioId", audio_ids),
            ):
                value = job.input_summary.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    destination.add(value)
            for key, destination in (
                ("batchId", batch_ids),
                ("itemId", item_ids),
            ):
                value = job.input_summary.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    destination.add(value)
        if batch_ids or item_ids:
            statement = select(GenerationBatchItem.audio_id).where(
                GenerationBatchItem.audio_id.is_not(None),
                or_(
                    GenerationBatchItem.batch_id.in_(batch_ids),
                    GenerationBatchItem.id.in_(item_ids),
                ),
            )
            audio_ids.update(
                audio_id
                for audio_id in session.scalars(statement)
                if audio_id is not None
            )
        return voice_ids, audio_ids

    @staticmethod
    def _audio_metadata_matches(
        audio: Audio,
        metadata: StoredAudioMetadata,
    ) -> bool:
        return (
            audio.audio_format == metadata.audio_format
            and audio.duration_seconds is not None
            and abs(audio.duration_seconds - metadata.duration_seconds) < 0.000001
            and audio.sample_rate == metadata.sample_rate
            and audio.channels == metadata.channels
            and audio.sample_width_bytes == metadata.sample_width_bytes
            and audio.file_size_bytes == metadata.file_size_bytes
        )

    @staticmethod
    def _set_audio_metadata(audio: Audio, metadata: StoredAudioMetadata) -> None:
        audio.audio_format = metadata.audio_format
        audio.duration_seconds = metadata.duration_seconds
        audio.sample_rate = metadata.sample_rate
        audio.channels = metadata.channels
        audio.sample_width_bytes = metadata.sample_width_bytes
        audio.file_size_bytes = metadata.file_size_bytes
        audio.error_summary = None

    @staticmethod
    def _entries(root: Path) -> list[Path]:
        try:
            return sorted(root.iterdir(), key=lambda path: path.name)
        except FileNotFoundError:
            return []

    @staticmethod
    def _regular_file(path: Path) -> bool:
        return path.is_file() and not path.is_symlink()

    @staticmethod
    def _orphan_issue(
        resource_type: str,
        resource_id: int | None,
        path: Path,
    ) -> ConsistencyIssue:
        return ConsistencyIssue(
            code="orphan_directory",
            resource_type=resource_type,
            resource_id=resource_id,
            message="Filesystem entry has no matching managed resource",
            paths=[str(path)],
        )

    @staticmethod
    def _unknown_file_issue(
        resource_type: str,
        resource_id: int,
        path: Path,
    ) -> ConsistencyIssue:
        return ConsistencyIssue(
            code="unknown_file",
            resource_type=resource_type,
            resource_id=resource_id,
            message="Managed resource directory contains an unknown entry",
            paths=[str(path)],
        )

    @staticmethod
    def _remove_path(path: Path) -> bool:
        if path.is_symlink() or not path.exists():
            return False
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    @staticmethod
    def _log_repair(issue: ConsistencyIssue) -> None:
        logger.bind(
            resource_type=issue.resource_type,
            resource_id=issue.resource_id or "-",
        ).info(
            "Consistency repair resource_type={} resource_id={} original_status={} "
            "target_status={} action={} result={}",
            issue.resource_type,
            issue.resource_id,
            issue.original_status,
            issue.target_status,
            issue.action,
            issue.result,
        )
