from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio import Audio
from backend.app.db.models.audio_tag import AudioTag
from backend.app.db.models.generation_batch import GenerationBatch
from backend.app.db.models.paper import Paper
from backend.app.db.models.voice import Voice
from backend.app.db.models.voice_tag import VoiceTag


class ResourceManagementRepository:
    def list_voices(self, session: Session, owner_id: int) -> list[Voice]:
        statement = (
            select(Voice)
            .options(selectinload(Voice.tags).selectinload(VoiceTag.translations))
            .where(Voice.author_id == owner_id)
            .order_by(Voice.id.desc())
        )
        return list(session.scalars(statement))

    def list_audios(self, session: Session, owner_id: int) -> list[Audio]:
        statement = (
            select(Audio)
            .options(selectinload(Audio.tags).selectinload(AudioTag.translations))
            .where(Audio.author_id == owner_id)
            .order_by(Audio.id.desc())
        )
        return list(session.scalars(statement))

    def list_generation_batches(
        self,
        session: Session,
        owner_id: int,
    ) -> list[GenerationBatch]:
        statement = (
            select(GenerationBatch)
            .options(selectinload(GenerationBatch.tags))
            .where(GenerationBatch.owner_id == owner_id)
            .order_by(GenerationBatch.id.desc())
        )
        return list(session.scalars(statement))

    def list_papers(self, session: Session, owner_id: int) -> list[Paper]:
        statement = (
            select(Paper).where(Paper.owner_id == owner_id).order_by(Paper.id.desc())
        )
        return list(session.scalars(statement))
