from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)


class AudioTagRepository:
    def get_by_id(self, session: Session, tag_id: int) -> AudioTag | None:
        return session.get(AudioTag, tag_id)

    def get_by_normalized_value(
        self,
        session: Session,
        tag_type: AudioTagType,
        normalized_value: str,
    ) -> AudioTag | None:
        statement = select(AudioTag).where(
            AudioTag.type == tag_type,
            AudioTag.normalized_value == normalized_value,
        )
        return session.scalar(statement)

    def create(
        self,
        session: Session,
        *,
        tag_type: AudioTagType,
        value: str,
        normalized_value: str,
    ) -> AudioTag:
        tag = AudioTag(
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
        tag: AudioTag,
        language: str,
        value: str,
        normalized_value: str,
    ) -> AudioTagTranslation:
        translation = AudioTagTranslation(
            tag=tag,
            language=language,
            value=value,
            normalized_value=normalized_value,
        )
        session.add(translation)
        session.flush()
        return translation
