from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio import Audio, AudioUtterance, audio_tag_associations
from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)
from backend.app.db.models.generation_batch import (
    generation_batch_tag_associations,
)


class AudioTagRepository:
    def get_by_id(self, session: Session, tag_id: int) -> AudioTag | None:
        return session.get(AudioTag, tag_id)

    def get_by_id_for_update(
        self,
        session: Session,
        tag_id: int,
    ) -> AudioTag | None:
        statement = select(AudioTag).where(AudioTag.id == tag_id).with_for_update()
        return session.scalar(statement)

    def list_tags(
        self,
        session: Session,
        tag_type: AudioTagType | None = None,
    ) -> list[AudioTag]:
        statement = (
            select(AudioTag)
            .options(selectinload(AudioTag.translations))
            .order_by(AudioTag.type, AudioTag.normalized_value, AudioTag.id)
        )
        if tag_type is not None:
            statement = statement.where(AudioTag.type == tag_type)
        return list(session.scalars(statement))

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

    def list_for_voice(
        self,
        session: Session,
        *,
        voice_id: int,
        current_normalized_value: str,
    ) -> list[AudioTag]:
        statement = (
            select(AudioTag, audio_tag_associations.c.audio_id)
            .join(
                audio_tag_associations,
                audio_tag_associations.c.tag_id == AudioTag.id,
            )
            .join(
                AudioUtterance,
                AudioUtterance.audio_id == audio_tag_associations.c.audio_id,
            )
            .options(selectinload(AudioTag.translations))
            .where(
                AudioTag.type == AudioTagType.VOICE,
                AudioUtterance.voice_id == voice_id,
            )
        )
        rows = list(session.execute(statement))
        if not rows:
            return []

        audio_ids = {audio_id for _, audio_id in rows}
        voice_ids_by_audio: dict[int, set[int | None]] = {
            audio_id: set() for audio_id in audio_ids
        }
        for audio_id, linked_voice_id in session.execute(
            select(AudioUtterance.audio_id, AudioUtterance.voice_id).where(
                AudioUtterance.audio_id.in_(audio_ids)
            )
        ):
            voice_ids_by_audio[audio_id].add(linked_voice_id)

        result: dict[int, AudioTag] = {}
        for tag, audio_id in rows:
            if (
                tag.normalized_value == current_normalized_value
                or voice_ids_by_audio[audio_id] == {voice_id}
            ):
                result[tag.id] = tag
        return list(result.values())

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

    def get_translation(
        self,
        session: Session,
        *,
        tag_id: int,
        language: str,
    ) -> AudioTagTranslation | None:
        statement = select(AudioTagTranslation).where(
            AudioTagTranslation.tag_id == tag_id,
            AudioTagTranslation.language == language,
        )
        return session.scalar(statement)

    def count_usage(self, session: Session, tag_id: int) -> int:
        audio_count = session.scalar(
            select(func.count())
            .select_from(audio_tag_associations)
            .where(audio_tag_associations.c.tag_id == tag_id)
        )
        batch_count = session.scalar(
            select(func.count())
            .select_from(generation_batch_tag_associations)
            .where(generation_batch_tag_associations.c.tag_id == tag_id)
        )
        return int(audio_count or 0) + int(batch_count or 0)

    def list_linked_audios(
        self,
        session: Session,
        tag_ids: set[int],
    ) -> list[tuple[int, Audio]]:
        if not tag_ids:
            return []
        statement = (
            select(audio_tag_associations.c.tag_id, Audio)
            .join(Audio, Audio.id == audio_tag_associations.c.audio_id)
            .where(audio_tag_associations.c.tag_id.in_(tag_ids))
            .order_by(audio_tag_associations.c.tag_id, Audio.id)
        )
        return [(tag_id, audio) for tag_id, audio in session.execute(statement)]

    def delete(self, session: Session, tag: AudioTag) -> None:
        session.delete(tag)
        session.flush()
