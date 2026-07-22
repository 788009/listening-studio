from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from backend.app.db.models.audio_tag import AudioTag, AudioTagType
from backend.app.repositories.audio_tags import AudioTagRepository
from backend.app.services.audio_storage import AudioStorage
from backend.app.services.authorization import (
    AuthorizationPrincipal,
    AuthorizationService,
    ResourceDescriptor,
    ResourceKind,
    ResourceStatus,
    ResourceVisibility,
)
from backend.app.services.tag_autocomplete import (
    MAX_AUTOCOMPLETE_RESULTS,
    autocomplete_tags,
)
from backend.app.services.tag_parser import TagDomain
from backend.app.services.tag_values import (
    TagTranslationInput,
    normalize_english_tag_value,
    normalize_tag_translations,
)


class AudioTagService:
    def __init__(self, repository: AudioTagRepository | None = None) -> None:
        self.repository = repository or AudioTagRepository()

    def create_tag(
        self,
        session: Session,
        *,
        tag_type: AudioTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> AudioTag:
        if not isinstance(tag_type, AudioTagType):
            raise DomainValidationError(
                "Audio tag type is invalid",
                details={"field": "type"},
            )
        english = normalize_english_tag_value(english_value)
        normalized_translations = normalize_tag_translations(translations)
        existing = self.repository.get_by_normalized_value(
            session,
            tag_type,
            english.normalized_value,
        )
        if existing:
            raise ConflictError("Audio tag already exists")

        try:
            tag = self.repository.create(
                session,
                tag_type=tag_type,
                value=english.value,
                normalized_value=english.normalized_value,
            )
            for translation in normalized_translations:
                self.repository.add_translation(
                    session,
                    tag=tag,
                    language=translation.language,
                    value=translation.value.value,
                    normalized_value=translation.value.normalized_value,
                )
            return tag
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("Audio tag or translation already exists") from exc

    def create_user_tag(
        self,
        session: Session,
        *,
        tag_type: AudioTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> AudioTag:
        if tag_type in {AudioTagType.AUTHOR, AudioTagType.OTHER} or (
            tag_type is AudioTagType.CATEGORY
            and normalize_english_tag_value(english_value).normalized_value
            == "full_paper"
        ):
            raise DomainValidationError(
                "System tags are managed by the system",
                details={"field": "type"},
            )
        return self.create_tag(
            session,
            tag_type=tag_type,
            english_value=english_value,
            translations=translations,
        )

    def get_tag(self, session: Session, tag_id: int) -> AudioTag:
        tag = self.repository.get_by_id(session, tag_id)
        if tag is None:
            raise NotFoundError("Audio tag not found")
        return tag

    def list_tags(
        self,
        session: Session,
        tag_type: AudioTagType | None = None,
    ) -> list[AudioTag]:
        return self.repository.list_tags(session, tag_type)

    def upsert_translation(
        self,
        session: Session,
        *,
        tag_id: int,
        translation: TagTranslationInput,
    ) -> AudioTag:
        tag = self.get_tag(session, tag_id)
        if self._is_system_tag(tag):
            raise ConflictError("System tags are managed by the system")
        normalized = normalize_tag_translations([translation])[0]
        existing = self.repository.get_translation(
            session,
            tag_id=tag.id,
            language=normalized.language,
        )
        try:
            if existing is None:
                self.repository.add_translation(
                    session,
                    tag=tag,
                    language=normalized.language,
                    value=normalized.value.value,
                    normalized_value=normalized.value.normalized_value,
                )
            else:
                existing.value = normalized.value.value
                existing.normalized_value = normalized.value.normalized_value
                session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError("Audio tag translation already exists") from exc
        return tag

    def delete_tag(self, session: Session, tag_id: int) -> None:
        tag = self.repository.get_by_id_for_update(session, tag_id)
        if tag is None:
            raise NotFoundError("Audio tag not found")
        if self._is_system_tag(tag):
            raise ConflictError("System tags are managed by the system")
        usage_count = self.repository.count_usage(session, tag.id)
        if usage_count:
            raise ConflictError(
                "Audio tag is still in use",
                details={"usageCount": usage_count},
            )
        self.repository.delete(session, tag)

    def autocomplete(
        self,
        session: Session,
        *,
        query: object,
        limit: int,
        principal: AuthorizationPrincipal,
        storage: AudioStorage,
    ) -> list[str]:
        self._validate_autocomplete_limit(limit)
        tags = self.repository.list_tags(session)
        author_tag_ids = {
            tag.id for tag in tags if tag.type is AudioTagType.AUTHOR
        }
        visible_author_ids: set[int] = set()
        authorization = AuthorizationService()
        for tag_id, audio in self.repository.list_linked_audios(
            session,
            author_tag_ids,
        ):
            descriptor = ResourceDescriptor(
                kind=ResourceKind.AUDIO,
                author_id=audio.author_id,
                visibility=ResourceVisibility(audio.visibility.value),
                status=ResourceStatus(audio.status.value),
                file_exists=storage.exists(audio.id),
            )
            if authorization.can_view(principal, descriptor):
                visible_author_ids.add(tag_id)

        visible_tags = [
            tag
            for tag in tags
            if tag.type is not AudioTagType.AUTHOR or tag.id in visible_author_ids
        ]
        return autocomplete_tags(
            visible_tags,
            query=query,
            domain=TagDomain.AUDIO,
            limit=limit,
        )

    @staticmethod
    def _validate_autocomplete_limit(limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_AUTOCOMPLETE_RESULTS
        ):
            raise DomainValidationError(
                "Autocomplete limit is invalid",
                details={"field": "limit"},
            )

    @staticmethod
    def _is_system_tag(tag: AudioTag) -> bool:
        return tag.type in {AudioTagType.AUTHOR, AudioTagType.OTHER} or (
            tag.type is AudioTagType.CATEGORY
            and tag.normalized_value == "full_paper"
        )
