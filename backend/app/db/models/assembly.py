from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SqlEnum
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.db.models.audio import Audio
    from backend.app.db.models.user import User


class AssemblySegmentType(str, Enum):
    AUDIO = "audio"
    SILENCE = "silence"
    PLACEHOLDER = "placeholder"
    SMART = "smart"


class AssemblyTemplate(Base):
    __tablename__ = "assembly_templates"
    __table_args__ = (
        UniqueConstraint(
            "normalized_title",
            name="uq_assembly_templates_normalized_title",
        ),
        Index("ix_assembly_templates_created", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    owner: Mapped["User"] = relationship()
    segments: Mapped[list["AssemblyTemplateSegment"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssemblyTemplateSegment.position",
    )


class AssemblyTemplateSegment(Base):
    __tablename__ = "assembly_template_segments"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_assembly_template_segments_position"),
        CheckConstraint(
            "repeat_count >= 1 AND repeat_count <= 10",
            name="ck_assembly_template_segments_repeat_count",
        ),
        CheckConstraint(
            "repeat_interval_milliseconds >= 0 AND repeat_interval_milliseconds <= 60000",
            name="ck_assembly_template_segments_repeat_interval",
        ),
        CheckConstraint(
            "silence_milliseconds >= 0 AND silence_milliseconds <= 60000",
            name="ck_assembly_template_segments_silence",
        ),
        UniqueConstraint(
            "template_id",
            "position",
            name="uq_assembly_template_segments_template_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("assembly_templates.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AssemblySegmentType] = mapped_column(
        SqlEnum(
            AssemblySegmentType,
            name="ck_assembly_template_segments_type",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    audio_id: Mapped[int | None] = mapped_column(
        ForeignKey("audios.id", ondelete="RESTRICT")
    )
    suggested_query: Mapped[str | None] = mapped_column(String(1024))
    silence_milliseconds: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    repeat_count: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    repeat_interval_milliseconds: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    include_text: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    include_topic: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped["AssemblyTemplate"] = relationship(back_populates="segments")
    audio: Mapped["Audio | None"] = relationship()
