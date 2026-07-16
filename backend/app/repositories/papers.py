from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.db.models.audio import Audio
from backend.app.db.models.paper import Paper, PaperItem, PaperPreset
from backend.app.db.models.user import User


class PaperRepository:
    def list_presets(self, session: Session, owner_id: int) -> list[PaperPreset]:
        statement = (
            select(PaperPreset)
            .where(
                or_(
                    PaperPreset.is_builtin.is_(True),
                    PaperPreset.owner_id == owner_id,
                )
            )
            .order_by(PaperPreset.is_builtin.desc(), PaperPreset.id)
        )
        return list(session.scalars(statement))

    def get_preset(self, session: Session, preset_id: int) -> PaperPreset | None:
        return session.get(PaperPreset, preset_id)

    def create_preset(
        self,
        session: Session,
        *,
        owner: User,
        name: str,
        intro_silence_milliseconds: int,
        inter_item_silence_milliseconds: int,
        repeat_count: int,
        outro_silence_milliseconds: int,
    ) -> PaperPreset:
        preset = PaperPreset(
            owner=owner,
            name=name,
            is_builtin=False,
            intro_silence_milliseconds=intro_silence_milliseconds,
            inter_item_silence_milliseconds=inter_item_silence_milliseconds,
            repeat_count=repeat_count,
            outro_silence_milliseconds=outro_silence_milliseconds,
        )
        session.add(preset)
        session.flush()
        return preset

    def delete_preset(self, session: Session, preset: PaperPreset) -> None:
        session.delete(preset)
        session.flush()

    def create_paper(
        self,
        session: Session,
        *,
        owner: User,
        preset: PaperPreset,
        title: str,
        normalized_title: str,
        audios: Sequence[Audio],
    ) -> Paper:
        paper = Paper(
            owner=owner,
            preset=preset,
            title=title,
            normalized_title=normalized_title,
            intro_silence_milliseconds=preset.intro_silence_milliseconds,
            inter_item_silence_milliseconds=preset.inter_item_silence_milliseconds,
            repeat_count=preset.repeat_count,
            outro_silence_milliseconds=preset.outro_silence_milliseconds,
        )
        session.add(paper)
        session.flush()
        for position, audio in enumerate(audios):
            session.add(PaperItem(paper=paper, audio=audio, position=position))
        session.flush()
        return paper

    def get_paper(self, session: Session, paper_id: int) -> Paper | None:
        statement = (
            select(Paper)
            .options(
                selectinload(Paper.items).selectinload(PaperItem.audio),
                selectinload(Paper.preset),
            )
            .where(Paper.id == paper_id)
        )
        return session.scalar(statement)

    def list_papers(
        self,
        session: Session,
        *,
        owner_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[Paper], int]:
        total = session.scalar(
            select(func.count())
            .select_from(Paper)
            .where(Paper.owner_id == owner_id)
        )
        statement = (
            select(Paper)
            .options(
                selectinload(Paper.items).selectinload(PaperItem.audio),
                selectinload(Paper.preset),
            )
            .where(Paper.owner_id == owner_id)
            .order_by(Paper.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(session.scalars(statement)), int(total or 0)
