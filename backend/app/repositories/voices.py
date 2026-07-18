from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio import Audio, AudioStatus, AudioUtterance
from backend.app.db.models.generation_batch import GenerationBatchSpeakerVoice
from backend.app.db.models.user import User
from backend.app.db.models.voice import Voice, VoiceSampleSource
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

    def synchronize_utterance_speaker_names(
        self,
        session: Session,
        *,
        voice_id: int,
        previous_title: str,
        title: str,
    ) -> int:
        if previous_title == title:
            return 0
        statement = (
            select(AudioUtterance)
            .options(
                selectinload(AudioUtterance.audio).selectinload(Audio.utterances)
            )
            .where(
                AudioUtterance.voice_id == voice_id,
                AudioUtterance.speaker_display_name == previous_title,
            )
        )
        utterances = list(session.scalars(statement))
        affected_audios = {item.audio_id: item.audio for item in utterances}
        for utterance in utterances:
            utterance.speaker_display_name = title
        for audio in affected_audios.values():
            if len(audio.utterances) > 1:
                audio.text = "\n".join(
                    f"{item.speaker_display_name}: {item.text}"
                    for item in audio.utterances
                )
        session.flush()
        return len(utterances)

    def count_active_audio_utterance_references(
        self,
        session: Session,
        voice_id: int,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(AudioUtterance)
            .join(Audio, Audio.id == AudioUtterance.audio_id)
            .where(
                AudioUtterance.voice_id == voice_id,
                Audio.status.in_({AudioStatus.PENDING, AudioStatus.PROCESSING}),
            )
        )
        return session.scalar(statement) or 0

    def count_generation_batch_references(
        self,
        session: Session,
        voice_id: int,
    ) -> int:
        statement = (
            select(func.count()).where(
                GenerationBatchSpeakerVoice.voice_id == voice_id
            )
        )
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
        sample_source: VoiceSampleSource,
        sample_audio_id: int | None,
        author_tag: VoiceTag,
    ) -> Voice:
        voice = Voice(
            author=author,
            title=title,
            normalized_title=normalized_title,
            sample_source=sample_source,
            sample_audio_id=sample_audio_id,
            tags=[author_tag],
        )
        session.add(voice)
        session.flush()
        return voice
