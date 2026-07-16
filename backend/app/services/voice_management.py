from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from backend.app.core.exceptions import ConflictError, NotFoundError
from backend.app.db.models.audio import Audio
from backend.app.db.models.voice import (
    Voice,
    VoiceSampleSource,
    VoiceStatus,
    VoiceVisibility,
)
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.repositories.voice_tags import VoiceTagRepository
from backend.app.repositories.voices import VoiceRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.authorization import (
    AuthorizationPrincipal,
    AuthorizationService,
    ResourceDescriptor,
    ResourceKind,
    ResourceStatus,
    ResourceVisibility,
)
from backend.app.services.tag_parser import ParsedQuery, TagType, parse_search_query
from backend.app.services.voice_storage import VoiceAsset, VoiceStorage
from backend.app.services.voices import VoiceService


@dataclass(frozen=True)
class VoiceListResult:
    items: list[Voice]
    total: int


class VoiceManagementService:
    def __init__(
        self,
        voice_storage: VoiceStorage,
        audio_storage: AudioStorage,
        *,
        repository: VoiceRepository | None = None,
        tag_repository: VoiceTagRepository | None = None,
    ) -> None:
        self.voice_storage = voice_storage
        self.audio_storage = audio_storage
        self.repository = repository or VoiceRepository()
        self.tag_repository = tag_repository or VoiceTagRepository()
        self.voice_service = VoiceService(voice_storage, self.repository)
        self.authorization = AuthorizationService()

    def get_visible(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice_id: int,
    ) -> Voice:
        voice = self.repository.get_by_id(session, voice_id)
        if voice is None:
            raise NotFoundError("Voice not found")
        self.authorization.require_view(principal, self._descriptor(voice))
        return voice

    def list_visible(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        *,
        page: int,
        page_size: int,
        author: str | None = None,
        status: VoiceStatus | None = None,
        visibility: VoiceVisibility | None = None,
        query: str | None = None,
    ) -> VoiceListResult:
        parsed_query = parse_search_query(query, "voice") if query else None
        voices = [
            voice
            for voice in self.repository.list_all(session)
            if self.authorization.can_view(principal, self._descriptor(voice))
            and self._matches_filters(
                voice,
                author=author,
                status=status,
                visibility=visibility,
                query=parsed_query,
            )
        ]
        total = len(voices)
        offset = (page - 1) * page_size
        return VoiceListResult(voices[offset : offset + page_size], total)

    def update(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice_id: int,
        *,
        title: str | None = None,
        gender_tag_ids: list[int] | None = None,
        visibility: VoiceVisibility | None = None,
        sample_source: VoiceSampleSource | None = None,
        sample_audio_id: int | None = None,
    ) -> Voice:
        voice = self.repository.get_by_id(session, voice_id)
        if voice is None:
            raise NotFoundError("Voice not found")
        descriptor = self._descriptor(voice)
        self.authorization.require_edit(principal, descriptor)
        if title is not None:
            self.voice_service.update_title(session, voice, title)
        if gender_tag_ids is not None:
            tags = self._gender_tags(session, gender_tag_ids)
            self.voice_service.replace_gender_tags(session, voice, tags)
        if sample_source is not None:
            self._set_sample_source(
                session,
                principal,
                voice,
                sample_source,
                sample_audio_id,
            )
        if visibility is not None:
            if visibility is VoiceVisibility.PUBLIC:
                self.authorization.require_publish(principal, descriptor)
                self._require_playable_example(session, principal, voice)
            self.voice_service.set_visibility(session, voice, visibility)
        return voice

    def resolve_sample_path(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice_id: int,
    ) -> Path:
        voice = self.repository.get_by_id(session, voice_id)
        if voice is None:
            raise NotFoundError("Voice not found")
        is_owner = bool(
            principal.user is not None and principal.user.id == voice.author_id
        )
        if not is_owner:
            self.authorization.require_use_for_synthesis(
                principal,
                self._descriptor(voice),
            )
        if voice.sample_source is VoiceSampleSource.ORIGINAL:
            path = self.voice_storage.path(voice.id, VoiceAsset.REFERENCE)
            if not path.is_file():
                raise NotFoundError("Voice original sample not found")
            return path
        audio = self._require_public_audio(
            session,
            principal,
            voice.sample_audio_id,
        )
        return self.audio_storage.path(audio.id)

    def delete(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice_id: int,
        *,
        request_id: str,
    ) -> None:
        voice = self.repository.get_by_id(session, voice_id)
        if voice is None:
            raise NotFoundError("Voice not found")
        self.authorization.require_delete(principal, self._descriptor(voice))
        if voice.status in {VoiceStatus.PENDING, VoiceStatus.PROCESSING}:
            raise ConflictError(
                "Voice has an active generation task",
                details={"activeTaskCount": 1, "audioUtteranceCount": 0},
            )
        utterance_count = self.repository.count_audio_utterance_references(
            session,
            voice.id,
        )
        batch_mapping_count = self.repository.count_generation_batch_references(
            session,
            voice.id,
        )
        if utterance_count or batch_mapping_count:
            raise ConflictError(
                "Voice is still in use",
                details={
                    "activeTaskCount": 0,
                    "audioUtteranceCount": utterance_count,
                    "batchVoiceMappingCount": batch_mapping_count,
                },
            )

        staged = self.voice_storage.stage_delete(voice.id)
        try:
            self.repository.delete(session, voice)
            session.commit()
        except Exception:
            session.rollback()
            self.voice_storage.restore_staged_delete(voice_id, staged)
            raise
        self.voice_storage.finalize_staged_delete(staged)
        logger.bind(request_id=request_id).info("Voice deleted voice_id={}", voice_id)

    def _descriptor(self, voice: Voice) -> ResourceDescriptor:
        return ResourceDescriptor(
            kind=ResourceKind.VOICE,
            author_id=voice.author_id,
            visibility=ResourceVisibility(voice.visibility.value),
            status=ResourceStatus(voice.status.value),
            file_exists=self.voice_storage.exists(voice.id),
        )

    def _require_playable_example(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice: Voice,
    ) -> None:
        if voice.sample_source is VoiceSampleSource.ORIGINAL:
            if not self.voice_storage.exists(voice.id, VoiceAsset.REFERENCE):
                raise ConflictError("Voice original sample is unavailable")
            return
        self._require_public_audio(session, principal, voice.sample_audio_id)

    def _set_sample_source(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        voice: Voice,
        sample_source: VoiceSampleSource,
        sample_audio_id: int | None,
    ) -> None:
        if sample_source is VoiceSampleSource.ORIGINAL:
            if not self.voice_storage.exists(voice.id, VoiceAsset.REFERENCE):
                raise ConflictError("Voice original sample is unavailable")
            self.voice_service.set_sample_source(
                session,
                voice,
                sample_source,
                None,
            )
            return
        audio = self._require_public_audio(session, principal, sample_audio_id)
        self.voice_service.set_sample_source(
            session,
            voice,
            sample_source,
            audio.id,
        )

    def _require_public_audio(
        self,
        session: Session,
        principal: AuthorizationPrincipal,
        audio_id: int | None,
    ) -> Audio:
        audio = session.get(Audio, audio_id)
        if audio is None:
            raise NotFoundError("Sample audio not found")
        descriptor = ResourceDescriptor(
            kind=ResourceKind.AUDIO,
            author_id=audio.author_id,
            visibility=ResourceVisibility(audio.visibility.value),
            status=ResourceStatus(audio.status.value),
            file_exists=self.audio_storage.exists(audio.id),
        )
        self.authorization.require_use_as_example(principal, descriptor)
        return audio

    def _gender_tags(self, session: Session, tag_ids: list[int]) -> list[VoiceTag]:
        tags: list[VoiceTag] = []
        for tag_id in dict.fromkeys(tag_ids):
            tag = self.tag_repository.get_by_id(session, tag_id)
            if tag is None or tag.type is not VoiceTagType.GENDER:
                raise NotFoundError("Voice gender tag not found")
            tags.append(tag)
        return tags

    @classmethod
    def _matches_filters(
        cls,
        voice: Voice,
        *,
        author: str | None,
        status: VoiceStatus | None,
        visibility: VoiceVisibility | None,
        query: ParsedQuery | None,
    ) -> bool:
        if author and (
            voice.author.user_id is None
            or voice.author.user_id.casefold() != author.casefold()
        ):
            return False
        if status is not None and voice.status is not status:
            return False
        if visibility is not None and voice.visibility is not visibility:
            return False
        if query is None:
            return True
        for term in query.tag_terms:
            if not any(
                cls._tag_matches_term(tag, term.type, term.normalized_value)
                for tag in voice.tags
            ):
                return False
        for keyword in query.keywords:
            if keyword in voice.normalized_title:
                continue
            if any(cls._tag_contains(tag, keyword) for tag in voice.tags):
                continue
            return False
        return True

    @staticmethod
    def _tag_matches_term(tag: VoiceTag, tag_type: TagType, value: str) -> bool:
        if tag.type.value != tag_type.value:
            return False
        return tag.normalized_value == value or any(
            translation.normalized_value == value for translation in tag.translations
        )

    @staticmethod
    def _tag_contains(tag: VoiceTag, value: str) -> bool:
        return value in tag.normalized_value or any(
            value in translation.normalized_value for translation in tag.translations
        )
