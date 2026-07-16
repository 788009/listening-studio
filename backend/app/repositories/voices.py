from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio import AudioUtterance
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceExampleMode
from backend.app.db.models.voice_tag import VoiceTag


class VoiceRepository:
    def get_by_id(self, session: Session, voice_id: int) -> Voice | None:
        return session.get(Voice, voice_id)

    def list_all(self, session: Session) -> list[Voice]:
        statement = (
            select(Voice)
            .options(
                selectinload(Voice.author),
                selectinload(Voice.tags).selectinload(VoiceTag.translations),
            )
            .order_by(Voice.id.desc())
        )
        return list(session.scalars(statement))

    def count_audio_utterance_references(
        self,
        session: Session,
        voice_id: int,
    ) -> int:
        statement = select(func.count()).where(AudioUtterance.voice_id == voice_id)
        return session.scalar(statement) or 0

    def delete(self, session: Session, voice: Voice) -> None:
        session.delete(voice)
        session.flush()

    def create(
        self,
        session: Session,
        *,
        author: User,
        title: str,
        normalized_title: str,
        example_mode: VoiceExampleMode,
        example_audio_id: int | None,
        author_tag: VoiceTag,
    ) -> Voice:
        voice = Voice(
            author=author,
            title=title,
            normalized_title=normalized_title,
            example_mode=example_mode,
            example_audio_id=example_audio_id,
            tags=[author_tag],
        )
        session.add(voice)
        session.flush()
        return voice
