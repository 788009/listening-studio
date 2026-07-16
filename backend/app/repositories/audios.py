from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from backend.app.db.models.audio import (
    Audio,
    AudioSourceType,
    AudioStatus,
    AudioUtterance,
    AudioVisibility,
    audio_tag_associations,
)
from backend.app.db.models.audio_tag import (
    AudioTag,
    AudioTagTranslation,
    AudioTagType,
)
from backend.app.db.models.user import User
from backend.app.services.tag_parser import ParsedQuery, ParsedTagTerm


@dataclass(frozen=True)
class AudioSearchCandidate:
    audio_id: int
    author_id: int


class AudioRepository:
    def get_by_id(self, session: Session, audio_id: int) -> Audio | None:
        return session.get(Audio, audio_id)

    def list_by_ids(self, session: Session, audio_ids: list[int]) -> list[Audio]:
        if not audio_ids:
            return []
        statement = (
            select(Audio)
            .options(
                selectinload(Audio.author),
                selectinload(Audio.tags).selectinload(AudioTag.translations),
                selectinload(Audio.utterances),
            )
            .where(Audio.id.in_(audio_ids))
            .order_by(Audio.id.desc())
        )
        return list(session.scalars(statement))

    def search_candidates(
        self,
        session: Session,
        *,
        principal_user_id: int | None,
        author: str | None,
        status: AudioStatus | None,
        visibility: AudioVisibility | None,
        query: ParsedQuery | None,
    ) -> list[AudioSearchCandidate]:
        public_ready = (
            (Audio.visibility == AudioVisibility.PUBLIC)
            & (Audio.status == AudioStatus.READY)
        )
        access = public_ready
        if principal_user_id is not None:
            access = or_(Audio.author_id == principal_user_id, public_ready)

        statement = select(Audio.id, Audio.author_id).where(access)
        if author:
            statement = statement.where(
                Audio.author.has(User.normalized_user_id == author.casefold())
            )
        if status is not None:
            statement = statement.where(Audio.status == status)
        if visibility is not None:
            statement = statement.where(Audio.visibility == visibility)
        if query is not None:
            for term in query.tag_terms:
                statement = statement.where(self._tag_term_exists(term))
            for keyword in query.keywords:
                pattern = f"%{self._escape_like(keyword)}%"
                statement = statement.where(
                    or_(
                        Audio.normalized_title.like(pattern, escape="\\"),
                        self._tag_keyword_exists(pattern),
                    )
                )
        statement = statement.order_by(Audio.id.desc())
        return [
            AudioSearchCandidate(audio_id=audio_id, author_id=author_id)
            for audio_id, author_id in session.execute(statement)
        ]

    @staticmethod
    def _tag_term_exists(term: ParsedTagTerm) -> ColumnElement[bool]:
        return (
            select(1)
            .select_from(
                audio_tag_associations.join(
                    AudioTag,
                    AudioTag.id == audio_tag_associations.c.tag_id,
                ).outerjoin(
                    AudioTagTranslation,
                    AudioTagTranslation.tag_id == AudioTag.id,
                )
            )
            .where(
                audio_tag_associations.c.audio_id == Audio.id,
                AudioTag.type == AudioTagType(term.type.value),
                or_(
                    AudioTag.normalized_value == term.normalized_value,
                    AudioTagTranslation.normalized_value == term.normalized_value,
                ),
            )
            .correlate(Audio)
            .exists()
        )

    @staticmethod
    def _tag_keyword_exists(pattern: str) -> ColumnElement[bool]:
        return (
            select(1)
            .select_from(
                audio_tag_associations.join(
                    AudioTag,
                    AudioTag.id == audio_tag_associations.c.tag_id,
                ).outerjoin(
                    AudioTagTranslation,
                    AudioTagTranslation.tag_id == AudioTag.id,
                )
            )
            .where(
                audio_tag_associations.c.audio_id == Audio.id,
                or_(
                    AudioTag.normalized_value.like(pattern, escape="\\"),
                    AudioTagTranslation.normalized_value.like(
                        pattern,
                        escape="\\",
                    ),
                ),
            )
            .correlate(Audio)
            .exists()
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def count_voice_sample_references(self, session: Session, audio_id: int) -> int:
        from backend.app.db.models.voice import Voice

        statement = select(func.count()).where(Voice.sample_audio_id == audio_id)
        return session.scalar(statement) or 0

    def delete(self, session: Session, audio: Audio) -> None:
        session.delete(audio)
        session.flush()

    def create(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        normalized_title: str,
        text: str,
        source_type: AudioSourceType,
        tags: Sequence[AudioTag],
    ) -> Audio:
        audio = Audio(
            author=author,
            title=title,
            normalized_title=normalized_title,
            text=text,
            source_type=source_type,
            tags=list(tags),
        )
        session.add(audio)
        session.flush()
        return audio

    def add_utterance(
        self,
        session: Session,
        *,
        audio: Audio,
        voice_id: int,
        speaker_display_name: str,
        text: str,
        position: int,
    ) -> AudioUtterance:
        utterance = AudioUtterance(
            audio=audio,
            voice_id=voice_id,
            speaker_display_name=speaker_display_name,
            text=text,
            position=position,
        )
        session.add(utterance)
        return utterance
