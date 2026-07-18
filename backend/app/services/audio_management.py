from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError, NotFoundError
from backend.app.db.models.audio import Audio, AudioStatus, AudioVisibility
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.repositories.audios import AudioRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.audios import AudioService
from backend.app.services.authorization import (
    AuthorizationPrincipal,
    AuthorizationService,
)
from backend.app.services.tag_parser import parse_search_query


@dataclass(frozen=True)
class AudioListResult:
    items: list[Audio]
    total: int


class AudioManagementService:
    def __init__(
        self,
        storage: AudioStorage,
        *,
        repository: AudioRepository | None = None,
        tag_repository: AudioTagRepository | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository or AudioRepository()
        self.tag_repository = tag_repository or AudioTagRepository()
        self.audio_service = AudioService(storage, self.repository)
        self.authorization = AuthorizationService()

    def get_visible(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        audio_id: int,
    ) -> Audio:
        audio = self.repository.get_by_id(session, audio_id)
        if audio is None:
            raise NotFoundError("Audio not found")
        self.authorization.require_view(principal, self.audio_service.descriptor(audio))
        return audio

    def list_visible(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        *,
        page: int,
        page_size: int,
        author: str | None = None,
        status: AudioStatus | None = None,
        visibility: AudioVisibility | None = None,
        query: str | None = None,
    ) -> AudioListResult:
        parsed = parse_search_query(query, "audio") if query else None
        principal_user_id = principal.user.id if principal.user is not None else None
        candidates = self.repository.search_candidates(
            session,
            principal_user_id=principal_user_id,
            author=author,
            status=status,
            visibility=visibility,
            query=parsed,
        )
        visible_ids = [
            candidate.audio_id
            for candidate in candidates
            if candidate.author_id == principal_user_id
            or self.storage.exists(candidate.audio_id)
        ]
        offset = (page - 1) * page_size
        page_ids = visible_ids[offset : offset + page_size]
        return AudioListResult(
            self.repository.list_by_ids(session, page_ids),
            len(visible_ids),
        )

    def update(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        audio_id: int,
        *,
        title: str | None,
        tag_ids: list[int] | None,
        visibility: AudioVisibility | None,
    ) -> Audio:
        audio = self.repository.get_by_id(session, audio_id)
        if audio is None:
            raise NotFoundError("Audio not found")
        descriptor = self.audio_service.descriptor(audio)
        self.authorization.require_edit(principal, descriptor)
        if title is not None:
            self.audio_service.update_title(session, audio, title)
        if tag_ids is not None:
            self.audio_service.replace_topic_category_tags(
                session,
                audio,
                self._tags(session, tag_ids),
            )
        if visibility is not None:
            if visibility is AudioVisibility.PUBLIC:
                self.authorization.require_publish(principal, descriptor)
            elif self.repository.count_voice_sample_references(session, audio.id):
                raise ConflictError(
                    "Audio is used as a voice example",
                    details={
                        "voiceIds": self._referencing_voice_ids(session, audio.id)
                    },
                )
            elif paper_reference_count := (
                self.repository.count_foreign_paper_item_references(
                    session,
                    audio_id=audio.id,
                    audio_owner_id=audio.author_id,
                )
            ):
                raise ConflictError(
                    "Audio is used by another teacher's paper",
                    details={"paperReferenceCount": paper_reference_count},
                )
            self.audio_service.set_visibility(session, audio, visibility)
        return audio

    def delete(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        audio_id: int,
        *,
        request_id: str,
    ) -> None:
        audio = self.repository.get_by_id(session, audio_id)
        if audio is None:
            raise NotFoundError("Audio not found")
        self.authorization.require_delete(
            principal,
            self.audio_service.descriptor(audio),
        )
        if audio.status in {AudioStatus.PENDING, AudioStatus.PROCESSING}:
            raise ConflictError(
                "Audio has an active generation task",
                details={"activeTaskCount": 1, "voiceIds": []},
            )
        voice_ids = self._referencing_voice_ids(session, audio.id)
        if voice_ids:
            raise ConflictError(
                "Audio is used as a voice example",
                details={"activeTaskCount": 0, "voiceIds": voice_ids},
            )
        batch_item_count = self.repository.count_generation_batch_references(
            session,
            audio.id,
        )
        if batch_item_count:
            raise ConflictError(
                "Audio is part of a generation batch",
                details={"batchItemCount": batch_item_count},
            )
        paper_item_count = self.repository.count_paper_item_references(
            session,
            audio.id,
        )
        paper_result_count = self.repository.count_paper_result_references(
            session,
            audio.id,
        )
        if paper_item_count or paper_result_count:
            raise ConflictError(
                "Audio is referenced by a paper",
                details={
                    "paperItemCount": paper_item_count,
                    "paperResultCount": paper_result_count,
                },
            )
        staged = self.storage.stage_delete(audio.id)
        try:
            self.repository.delete(session, audio)
            session.commit()
        except Exception:
            session.rollback()
            self.storage.restore_staged_delete(audio_id, staged)
            raise
        self.storage.finalize_staged_delete(staged)
        logger.bind(
            request_id=request_id,
            user_db_id=audio.author_id,
            resource_type="audio",
            resource_id=audio_id,
        ).info("Audio deleted audio_id={}", audio_id)

    def _tags(self, session: Session, tag_ids: list[int]) -> list[AudioTag]:
        tags: list[AudioTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = self.tag_repository.get_by_id(session, tag_id)
            if tag is None or tag.type not in {
                AudioTagType.TOPIC,
                AudioTagType.CATEGORY,
            }:
                raise NotFoundError("Audio tag not found")
            tags.append(tag)
        return tags

    @staticmethod
    def _referencing_voice_ids(session: Session, audio_id: int) -> list[int]:
        from sqlalchemy import select

        from backend.app.db.models.voice import Voice

        return list(
            session.scalars(
                select(Voice.id)
                .where(Voice.sample_audio_id == audio_id)
                .order_by(Voice.id)
            )
        )
