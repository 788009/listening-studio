from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceExampleMode
from backend.app.db.models.voice_tag import VoiceTag


class VoiceRepository:
    def get_by_id(self, session: Session, voice_id: int) -> Voice | None:
        return session.get(Voice, voice_id)

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
