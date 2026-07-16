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
from backend.app.services.tag_parser import ParsedQuery, TagType, parse_search_query


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
        audios = [
            audio
            for audio in self.repository.list_all(session)
            if self.authorization.can_view(
                principal,
                self.audio_service.descriptor(audio),
            )
            and self._matches(audio, author, status, visibility, parsed)
        ]
        offset = (page - 1) * page_size
        return AudioListResult(audios[offset : offset + page_size], len(audios))

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
            self.audio_service.replace_user_tags(
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
        staged = self.storage.stage_delete(audio.id)
        try:
            self.repository.delete(session, audio)
            session.commit()
        except Exception:
            session.rollback()
            self.storage.restore_staged_delete(audio_id, staged)
            raise
        self.storage.finalize_staged_delete(staged)
        logger.bind(request_id=request_id).info("Audio deleted audio_id={}", audio_id)

    def _tags(self, session: Session, tag_ids: list[int]) -> list[AudioTag]:
        tags: list[AudioTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = self.tag_repository.get_by_id(session, tag_id)
            if tag is None or tag.type is AudioTagType.AUTHOR:
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

    @classmethod
    def _matches(
        cls,
        audio: Audio,
        author: str | None,
        status: AudioStatus | None,
        visibility: AudioVisibility | None,
        query: ParsedQuery | None,
    ) -> bool:
        if author and (
            audio.author.user_id is None
            or audio.author.user_id.casefold() != author.casefold()
        ):
            return False
        if status is not None and audio.status is not status:
            return False
        if visibility is not None and audio.visibility is not visibility:
            return False
        if query is None:
            return True
        for term in query.tag_terms:
            if not any(
                cls._term(tag, term.type, term.normalized_value)
                for tag in audio.tags
            ):
                return False
        for keyword in query.keywords:
            if keyword in audio.normalized_title or any(
                cls._contains(tag, keyword) for tag in audio.tags
            ):
                continue
            return False
        return True

    @staticmethod
    def _term(tag: AudioTag, tag_type: TagType, value: str) -> bool:
        return tag.type.value == tag_type.value and (
            tag.normalized_value == value
            or any(item.normalized_value == value for item in tag.translations)
        )

    @staticmethod
    def _contains(tag: AudioTag, value: str) -> bool:
        return value in tag.normalized_value or any(
            value in item.normalized_value for item in tag.translations
        )
