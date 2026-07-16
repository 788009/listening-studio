from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.voice import voice_tag_associations
from backend.app.db.models.voice_tag import (
    VoiceTag,
    VoiceTagTranslation,
    VoiceTagType,
)


class VoiceTagRepository:
    def get_by_id(self, session: Session, tag_id: int) -> VoiceTag | None:
        return session.get(VoiceTag, tag_id)

    def get_by_id_for_update(
        self,
        session: Session,
        tag_id: int,
    ) -> VoiceTag | None:
        statement = select(VoiceTag).where(VoiceTag.id == tag_id).with_for_update()
        return session.scalar(statement)

    def list_tags(
        self,
        session: Session,
        tag_type: VoiceTagType | None = None,
    ) -> list[VoiceTag]:
        statement = (
            select(VoiceTag)
            .options(selectinload(VoiceTag.translations))
            .order_by(VoiceTag.type, VoiceTag.normalized_value, VoiceTag.id)
        )
        if tag_type is not None:
            statement = statement.where(VoiceTag.type == tag_type)
        return list(session.scalars(statement))

    def get_by_normalized_value(
        self,
        session: Session,
        tag_type: VoiceTagType,
        normalized_value: str,
    ) -> VoiceTag | None:
        statement = select(VoiceTag).where(
            VoiceTag.type == tag_type,
            VoiceTag.normalized_value == normalized_value,
        )
        return session.scalar(statement)

    def create(
        self,
        session: Session,
        *,
        tag_type: VoiceTagType,
        value: str,
        normalized_value: str,
    ) -> VoiceTag:
        tag = VoiceTag(
            type=tag_type,
            value=value,
            normalized_value=normalized_value,
        )
        session.add(tag)
        session.flush()
        return tag

    def add_translation(
        self,
        session: Session,
        *,
        tag: VoiceTag,
        language: str,
        value: str,
        normalized_value: str,
    ) -> VoiceTagTranslation:
        translation = VoiceTagTranslation(
            tag=tag,
            language=language,
            value=value,
            normalized_value=normalized_value,
        )
        session.add(translation)
        session.flush()
        return translation

    def get_translation(
        self,
        session: Session,
        *,
        tag_id: int,
        language: str,
    ) -> VoiceTagTranslation | None:
        statement = select(VoiceTagTranslation).where(
            VoiceTagTranslation.tag_id == tag_id,
            VoiceTagTranslation.language == language,
        )
        return session.scalar(statement)

    def count_usage(self, session: Session, tag_id: int) -> int:
        statement = (
            select(func.count())
            .select_from(voice_tag_associations)
            .where(voice_tag_associations.c.tag_id == tag_id)
        )
        return session.scalar(statement) or 0

    def delete(self, session: Session, tag: VoiceTag) -> None:
        session.delete(tag)
        session.flush()
