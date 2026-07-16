from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.exceptions import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
)
from backend.app.db.models.voice_tag import VoiceTag, VoiceTagType
from backend.app.repositories.voice_tags import VoiceTagRepository
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
from backend.app.services.voice_storage import VoiceStorage


class VoiceTagService:
    def __init__(self, repository: VoiceTagRepository | None = None) -> None:
        self.repository = repository or VoiceTagRepository()

    def create_tag(
        self,
        session: Session,
        *,
        tag_type: VoiceTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> VoiceTag:
        if not isinstance(tag_type, VoiceTagType):
            raise DomainValidationError(
                "Voice tag type is invalid",
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
            raise ConflictError("Voice tag already exists")

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
            raise ConflictError("Voice tag or translation already exists") from exc

    def create_user_tag(
        self,
        session: Session,
        *,
        tag_type: VoiceTagType,
        english_value: object,
        translations: Iterable[TagTranslationInput] = (),
    ) -> VoiceTag:
        if tag_type is VoiceTagType.AUTHOR:
            raise DomainValidationError(
                "Author tags are managed by the system",
                details={"field": "type"},
            )
        return self.create_tag(
            session,
            tag_type=tag_type,
            english_value=english_value,
            translations=translations,
        )

    def get_tag(self, session: Session, tag_id: int) -> VoiceTag:
        tag = self.repository.get_by_id(session, tag_id)
        if tag is None:
            raise NotFoundError("Voice tag not found")
        return tag

    def list_tags(
        self,
        session: Session,
        tag_type: VoiceTagType | None = None,
    ) -> list[VoiceTag]:
        return self.repository.list_tags(session, tag_type)

    def upsert_translation(
        self,
        session: Session,
        *,
        tag_id: int,
        translation: TagTranslationInput,
    ) -> VoiceTag:
        tag = self.get_tag(session, tag_id)
        if tag.type is VoiceTagType.AUTHOR:
            raise ConflictError("Author tags are managed by the system")
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
            raise ConflictError("Voice tag translation already exists") from exc
        return tag

    def delete_tag(self, session: Session, tag_id: int) -> None:
        tag = self.repository.get_by_id_for_update(session, tag_id)
        if tag is None:
            raise NotFoundError("Voice tag not found")
        if tag.type is VoiceTagType.AUTHOR:
            raise ConflictError("Author tags are managed by the system")
        usage_count = self.repository.count_usage(session, tag.id)
        if usage_count:
            raise ConflictError(
                "Voice tag is still in use",
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
        storage: VoiceStorage,
    ) -> list[str]:
        self._validate_autocomplete_limit(limit)
        tags = self.repository.list_tags(session)
        author_tag_ids = {
            tag.id for tag in tags if tag.type is VoiceTagType.AUTHOR
        }
        visible_author_ids: set[int] = set()
        authorization = AuthorizationService()
        for tag_id, voice in self.repository.list_linked_voices(
            session,
            author_tag_ids,
        ):
            descriptor = ResourceDescriptor(
                kind=ResourceKind.VOICE,
                author_id=voice.author_id,
                visibility=ResourceVisibility(voice.visibility.value),
                status=ResourceStatus(voice.status.value),
                file_exists=storage.exists(voice.id),
            )
            if authorization.can_view(principal, descriptor):
                visible_author_ids.add(tag_id)

        visible_tags = [
            tag
            for tag in tags
            if tag.type is not VoiceTagType.AUTHOR or tag.id in visible_author_ids
        ]
        return autocomplete_tags(
            visible_tags,
            query=query,
            domain=TagDomain.VOICE,
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
