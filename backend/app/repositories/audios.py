from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from backend.app.db.models.audio import Audio, AudioSourceType, AudioUtterance
from backend.app.db.models.audio_tag import AudioTag
from backend.app.db.models.user import User


class AudioRepository:
    def get_by_id(self, session: Session, audio_id: int) -> Audio | None:
        return session.get(Audio, audio_id)

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
