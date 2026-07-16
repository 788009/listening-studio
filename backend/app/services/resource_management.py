from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.auth import Principal
from backend.app.core.exceptions import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
)
from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.generation_batch import GenerationBatch
from backend.app.db.models.paper import Paper
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceStatus, VoiceVisibility
from backend.app.repositories.audios import AudioRepository
from backend.app.repositories.resource_management import ResourceManagementRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.audio_management import AudioManagementService
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.voice_management import VoiceManagementService
from backend.app.services.voice_storage import VoiceStorage


class ManagedResourceKind(str, Enum):
    VOICE = "voice"
    AUDIO = "audio"
    GENERATION_BATCH = "generation_batch"
    PAPER = "paper"


class BulkOutcome(str, Enum):
    SUCCESS = "success"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(frozen=True)
class ManagedTag:
    id: int
    type: str
    value: str


@dataclass(frozen=True)
class ManagedReference:
    type: str
    count: int


@dataclass(frozen=True)
class ManagedResource:
    id: int
    kind: ManagedResourceKind
    title: str
    status: str
    visibility: str | None
    tags: list[ManagedTag]
    created_at: datetime
    references: list[ManagedReference]
    can_delete: bool


@dataclass(frozen=True)
class ManagedResourceList:
    items: list[ManagedResource]
    total: int


@dataclass(frozen=True)
class BulkItemResult:
    id: int
    outcome: BulkOutcome
    message: str


@dataclass(frozen=True)
class BulkUpdateResult:
    items: list[BulkItemResult]

    @property
    def success_count(self) -> int:
        return sum(item.outcome is BulkOutcome.SUCCESS for item in self.items)

    @property
    def conflict_count(self) -> int:
        return sum(item.outcome is BulkOutcome.CONFLICT for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.outcome is BulkOutcome.FAILED for item in self.items)


class ResourceManagementService:
    _statuses = {
        ManagedResourceKind.VOICE: {"pending", "processing", "ready", "failed"},
        ManagedResourceKind.AUDIO: {"pending", "processing", "ready", "failed"},
        ManagedResourceKind.GENERATION_BATCH: {
            "pending",
            "processing",
            "completed",
            "failed",
            "cancelled",
        },
        ManagedResourceKind.PAPER: {"pending", "processing", "ready", "failed"},
    }

    def __init__(
        self,
        data_dir: Path,
        *,
        repository: ResourceManagementRepository | None = None,
    ) -> None:
        self.repository = repository or ResourceManagementRepository()
        self.voice_repository = VoiceRepository()
        self.audio_repository = AudioRepository()
        self.voice_service = VoiceManagementService(
            VoiceStorage(data_dir),
            AudioStorage(data_dir),
            repository=self.voice_repository,
        )
        self.audio_service = AudioManagementService(
            AudioStorage(data_dir),
            repository=self.audio_repository,
        )

    def list_owned(
        self,
        session: Session,
        owner: User,
        *,
        kind: ManagedResourceKind,
        page: int,
        page_size: int,
        status: str | None,
        visibility: str | None,
        tag_ids: list[int],
        created_from: datetime | None,
        created_before: datetime | None,
        query: str | None,
    ) -> ManagedResourceList:
        self._validate_filters(
            kind,
            status=status,
            visibility=visibility,
            tag_ids=tag_ids,
            created_from=created_from,
            created_before=created_before,
        )
        resources = self._models(session, owner.id, kind)
        normalized_query = self._normalize_query(query)
        filtered = [
            resource
            for resource in resources
            if self._matches(
                resource,
                status=status,
                visibility=visibility,
                tag_ids=tag_ids,
                created_from=created_from,
                created_before=created_before,
                query=normalized_query,
            )
        ]
        offset = (page - 1) * page_size
        page_items = filtered[offset : offset + page_size]
        return ManagedResourceList(
            [self._resource(session, kind, item) for item in page_items],
            len(filtered),
        )

    def bulk_update(
        self,
        session: Session,
        owner: User,
        *,
        kind: ManagedResourceKind,
        resource_ids: list[int],
        visibility: str | None,
        tag_ids: list[int] | None,
        request_id: str,
    ) -> BulkUpdateResult:
        if kind not in {ManagedResourceKind.VOICE, ManagedResourceKind.AUDIO}:
            raise DomainValidationError(
                "Bulk updates support only voices and audios",
                details={"field": "kind"},
            )
        if visibility is None and tag_ids is None:
            raise DomainValidationError("Bulk update has no changes")
        if visibility is not None and visibility not in {"private", "public"}:
            raise DomainValidationError(
                "Resource visibility is invalid",
                details={"field": "visibility"},
            )

        principal = Principal(owner)
        results: list[BulkItemResult] = []
        for resource_id in resource_ids:
            try:
                with session.begin_nested():
                    self._update_one(
                        session,
                        principal,
                        kind=kind,
                        resource_id=resource_id,
                        visibility=visibility,
                        tag_ids=tag_ids,
                    )
                    session.flush()
                results.append(
                    BulkItemResult(
                        resource_id,
                        BulkOutcome.SUCCESS,
                        "Resource updated",
                    )
                )
            except ConflictError as exc:
                results.append(
                    BulkItemResult(resource_id, BulkOutcome.CONFLICT, exc.message)
                )
            except (NotFoundError, ForbiddenError):
                results.append(
                    BulkItemResult(
                        resource_id,
                        BulkOutcome.FAILED,
                        "Resource is unavailable",
                    )
                )
            except DomainError as exc:
                results.append(
                    BulkItemResult(resource_id, BulkOutcome.FAILED, exc.message)
                )
            except Exception as exc:
                logger.bind(request_id=request_id).error(
                    "Bulk resource update failed resource_kind={} resource_id={} "
                    "exception_type={}",
                    kind.value,
                    resource_id,
                    type(exc).__name__,
                )
                results.append(
                    BulkItemResult(
                        resource_id,
                        BulkOutcome.FAILED,
                        "Resource update failed",
                    )
                )
        logger.bind(request_id=request_id).info(
            "Bulk resource update completed resource_kind={} requested={} "
            "succeeded={} conflicts={} failed={}",
            kind.value,
            len(resource_ids),
            sum(item.outcome is BulkOutcome.SUCCESS for item in results),
            sum(item.outcome is BulkOutcome.CONFLICT for item in results),
            sum(item.outcome is BulkOutcome.FAILED for item in results),
        )
        return BulkUpdateResult(results)

    def _update_one(
        self,
        session: Session,
        principal: Principal,
        *,
        kind: ManagedResourceKind,
        resource_id: int,
        visibility: str | None,
        tag_ids: list[int] | None,
    ) -> None:
        if kind is ManagedResourceKind.VOICE:
            self.voice_service.update(
                session,
                principal,
                resource_id,
                gender_tag_ids=tag_ids,
                visibility=(
                    VoiceVisibility(visibility) if visibility is not None else None
                ),
            )
            return
        self.audio_service.update(
            session,
            principal,
            resource_id,
            title=None,
            tag_ids=tag_ids,
            visibility=(
                AudioVisibility(visibility) if visibility is not None else None
            ),
        )

    def _models(
        self,
        session: Session,
        owner_id: int,
        kind: ManagedResourceKind,
    ) -> list[Voice] | list[Audio] | list[GenerationBatch] | list[Paper]:
        if kind is ManagedResourceKind.VOICE:
            return self.repository.list_voices(session, owner_id)
        if kind is ManagedResourceKind.AUDIO:
            return self.repository.list_audios(session, owner_id)
        if kind is ManagedResourceKind.GENERATION_BATCH:
            return self.repository.list_generation_batches(session, owner_id)
        return self.repository.list_papers(session, owner_id)

    def _resource(
        self,
        session: Session,
        kind: ManagedResourceKind,
        model: Voice | Audio | GenerationBatch | Paper,
    ) -> ManagedResource:
        references: list[ManagedReference] = []
        visibility: str | None = None
        tags: list[ManagedTag] = []
        can_delete = False
        if isinstance(model, Voice):
            visibility = model.visibility.value
            tags = self._tags(model.tags)
            references = self._voice_references(session, model)
            can_delete = not references
        elif isinstance(model, Audio):
            visibility = model.visibility.value
            tags = self._tags(model.tags)
            references = self._audio_references(session, model)
            can_delete = not references
        elif isinstance(model, GenerationBatch):
            tags = self._tags(model.tags)
        title = (
            f"Generation batch {model.id}"
            if isinstance(model, GenerationBatch)
            else model.title
        )
        return ManagedResource(
            id=model.id,
            kind=kind,
            title=title,
            status=model.status.value,
            visibility=visibility,
            tags=tags,
            created_at=model.created_at,
            references=references,
            can_delete=can_delete,
        )

    def _voice_references(
        self,
        session: Session,
        voice: Voice,
    ) -> list[ManagedReference]:
        values = {
            "active_task": int(
                voice.status in {VoiceStatus.PENDING, VoiceStatus.PROCESSING}
            ),
            "audio_utterance": self.voice_repository.count_audio_utterance_references(
                session,
                voice.id,
            ),
            "generation_batch": self.voice_repository.count_generation_batch_references(
                session,
                voice.id,
            ),
        }
        return [
            ManagedReference(reference_type, count)
            for reference_type, count in values.items()
            if count
        ]

    def _audio_references(
        self,
        session: Session,
        audio: Audio,
    ) -> list[ManagedReference]:
        values = {
            "active_task": int(
                audio.status in {AudioStatus.PENDING, AudioStatus.PROCESSING}
            ),
            "voice_sample": self.audio_repository.count_voice_sample_references(
                session,
                audio.id,
            ),
            "generation_batch": self.audio_repository.count_generation_batch_references(
                session,
                audio.id,
            ),
            "paper_item": self.audio_repository.count_paper_item_references(
                session,
                audio.id,
            ),
            "paper_result": self.audio_repository.count_paper_result_references(
                session,
                audio.id,
            ),
        }
        return [
            ManagedReference(reference_type, count)
            for reference_type, count in values.items()
            if count
        ]

    @staticmethod
    def _tags(values: Iterable[Any]) -> list[ManagedTag]:
        return [ManagedTag(tag.id, tag.type.value, tag.value) for tag in values]

    @classmethod
    def _validate_filters(
        cls,
        kind: ManagedResourceKind,
        *,
        status: str | None,
        visibility: str | None,
        tag_ids: list[int],
        created_from: datetime | None,
        created_before: datetime | None,
    ) -> None:
        if status is not None and status not in cls._statuses[kind]:
            raise DomainValidationError(
                "Resource status is invalid",
                details={"field": "status"},
            )
        if visibility is not None:
            if kind not in {ManagedResourceKind.VOICE, ManagedResourceKind.AUDIO}:
                raise DomainValidationError(
                    "Visibility filter is not supported for this resource",
                    details={"field": "visibility"},
                )
            if visibility not in {"private", "public"}:
                raise DomainValidationError(
                    "Resource visibility is invalid",
                    details={"field": "visibility"},
                )
        if tag_ids and kind is ManagedResourceKind.PAPER:
            raise DomainValidationError(
                "Tag filter is not supported for papers",
                details={"field": "tagIds"},
            )
        if (
            created_from is not None
            and created_before is not None
            and cls._instant(created_from) >= cls._instant(created_before)
        ):
            raise DomainValidationError(
                "Creation time range is invalid",
                details={"field": "createdBefore"},
            )

    @classmethod
    def _matches(
        cls,
        model: Voice | Audio | GenerationBatch | Paper,
        *,
        status: str | None,
        visibility: str | None,
        tag_ids: list[int],
        created_from: datetime | None,
        created_before: datetime | None,
        query: str | None,
    ) -> bool:
        if status is not None and model.status.value != status:
            return False
        if visibility is not None:
            model_visibility = getattr(model, "visibility", None)
            if model_visibility is None or model_visibility.value != visibility:
                return False
        model_tags = getattr(model, "tags", [])
        model_tag_ids = {tag.id for tag in model_tags}
        if any(tag_id not in model_tag_ids for tag_id in tag_ids):
            return False
        created_at = cls._instant(model.created_at)
        if created_from is not None and created_at < cls._instant(created_from):
            return False
        if created_before is not None and created_at >= cls._instant(created_before):
            return False
        if query is not None:
            title = (
                f"Generation batch {model.id}"
                if isinstance(model, GenerationBatch)
                else model.title
            )
            if query not in unicodedata.normalize("NFKC", title).casefold():
                return False
        return True

    @staticmethod
    def _normalize_query(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFKC", value.strip()).casefold()
        return normalized or None

    @staticmethod
    def _instant(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
