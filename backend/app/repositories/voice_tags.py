from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.voice_tag import (
    VoiceTag,
    VoiceTagTranslation,
    VoiceTagType,
)


class VoiceTagRepository:
    def get_by_id(self, session: Session, tag_id: int) -> VoiceTag | None:
        return session.get(VoiceTag, tag_id)

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
