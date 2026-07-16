from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.db.models.audio import Audio
    from backend.app.db.models.user import User


class PaperStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class PaperPreset(Base):
    __tablename__ = "paper_presets"
    __table_args__ = (
        CheckConstraint(
            "(is_builtin AND owner_id IS NULL) OR "
            "(NOT is_builtin AND owner_id IS NOT NULL)",
            name="ck_paper_presets_ownership",
        ),
        CheckConstraint(
            "intro_silence_milliseconds >= 0 AND "
            "intro_silence_milliseconds <= 60000",
            name="ck_paper_presets_intro_silence",
        ),
        CheckConstraint(
            "inter_item_silence_milliseconds >= 0 AND "
            "inter_item_silence_milliseconds <= 60000",
            name="ck_paper_presets_inter_item_silence",
        ),
        CheckConstraint(
            "repeat_count >= 1 AND repeat_count <= 10",
            name="ck_paper_presets_repeat_count",
        ),
        CheckConstraint(
            "outro_silence_milliseconds >= 0 AND "
            "outro_silence_milliseconds <= 60000",
            name="ck_paper_presets_outro_silence",
        ),
        Index("ix_paper_presets_owner", "owner_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    intro_silence_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    inter_item_silence_milliseconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outro_silence_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    owner: Mapped["User | None"] = relationship()


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(
            "intro_silence_milliseconds >= 0 AND "
            "intro_silence_milliseconds <= 60000",
            name="ck_papers_intro_silence",
        ),
        CheckConstraint(
            "inter_item_silence_milliseconds >= 0 AND "
            "inter_item_silence_milliseconds <= 60000",
            name="ck_papers_inter_item_silence",
        ),
        CheckConstraint(
            "repeat_count >= 1 AND repeat_count <= 10",
            name="ck_papers_repeat_count",
        ),
        CheckConstraint(
            "outro_silence_milliseconds >= 0 AND "
            "outro_silence_milliseconds <= 60000",
            name="ck_papers_outro_silence",
        ),
        Index("ix_papers_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    preset_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_presets.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[PaperStatus] = mapped_column(
        SqlEnum(
            PaperStatus,
            name="ck_papers_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=PaperStatus.PENDING,
        server_default=PaperStatus.PENDING.value,
        nullable=False,
    )
    intro_silence_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    inter_item_silence_milliseconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outro_silence_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    result_audio_id: Mapped[int | None] = mapped_column(
        ForeignKey("audios.id", ondelete="RESTRICT"),
        unique=True,
    )
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    owner: Mapped["User"] = relationship()
    preset: Mapped[PaperPreset | None] = relationship()
    result_audio: Mapped["Audio | None"] = relationship(
        foreign_keys=[result_audio_id]
    )
    items: Mapped[list["PaperItem"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PaperItem.position",
    )


class PaperItem(Base):
    __tablename__ = "paper_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_paper_items_position"),
        UniqueConstraint(
            "paper_id",
            "position",
            name="uq_paper_items_paper_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    audio_id: Mapped[int] = mapped_column(
        ForeignKey("audios.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    paper: Mapped[Paper] = relationship(back_populates="items")
    audio: Mapped["Audio"] = relationship(foreign_keys=[audio_id])
