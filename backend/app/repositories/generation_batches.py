from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio_tag import AudioTag
from backend.app.db.models.generation_batch import (
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchSpeakerVoice,
)
from backend.app.db.models.job import Job
from backend.app.db.models.user import User


class GenerationBatchRepository:
    _load_options = (
        selectinload(GenerationBatch.tags),
        selectinload(GenerationBatch.items).selectinload(GenerationBatchItem.audio),
        selectinload(GenerationBatch.speaker_voices),
    )

    def create(
        self,
        session: Session,
        *,
        owner: User,
        job: Job,
        question_types: list[str],
        requested_count: int,
        tags: Sequence[AudioTag],
        speaker_voices: Sequence[tuple[str, str, int]],
    ) -> GenerationBatch:
        batch = GenerationBatch(
            owner=owner,
            job=job,
            question_types=question_types,
            requested_count=requested_count,
            tags=list(tags),
        )
        session.add(batch)
        session.flush()
        for position in range(requested_count):
            session.add(GenerationBatchItem(batch=batch, position=position))
        for speaker, normalized_speaker, voice_id in speaker_voices:
            session.add(
                GenerationBatchSpeakerVoice(
                    batch=batch,
                    speaker=speaker,
                    normalized_speaker=normalized_speaker,
                    voice_id=voice_id,
                )
            )
        session.flush()
        return batch

    def get_item(
        self,
        session: Session,
        item_id: int,
    ) -> GenerationBatchItem | None:
        return session.get(GenerationBatchItem, item_id)

    def get_by_id(self, session: Session, batch_id: int) -> GenerationBatch | None:
        statement = (
            select(GenerationBatch)
            .options(*self._load_options)
            .where(GenerationBatch.id == batch_id)
        )
        return session.scalar(statement)

    def list_for_owner(
        self,
        session: Session,
        *,
        owner_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[GenerationBatch], int]:
        filters = [GenerationBatch.owner_id == owner_id]
        total = session.scalar(
            select(func.count()).select_from(GenerationBatch).where(*filters)
        )
        statement = (
            select(GenerationBatch)
            .options(*self._load_options)
            .where(*filters)
            .order_by(GenerationBatch.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(session.scalars(statement)), int(total or 0)
