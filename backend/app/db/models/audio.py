from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.db.models.audio_tag import AudioTag
    from backend.app.db.models.user import User
    from backend.app.db.models.voice import Voice


class AudioStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AudioVisibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class AudioSourceType(str, Enum):
    SINGLE_SPEAKER = "single_speaker"
    MULTI_TURN = "multi_turn"
    CORPUS = "corpus"
    ASSEMBLY = "assembly"


audio_tag_associations = Table(
    "audio_tag_associations",
    Base.metadata,
    Column(
        "audio_id",
        ForeignKey("audios.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("audio_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Audio(Base):
    __tablename__ = "audios"
    __table_args__ = (Index("ix_audios_normalized_title", "normalized_title"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[AudioSourceType] = mapped_column(
        SqlEnum(
            AudioSourceType,
            name="ck_audios_source_type",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    status: Mapped[AudioStatus] = mapped_column(
        SqlEnum(
            AudioStatus,
            name="ck_audios_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=AudioStatus.PENDING,
        server_default=AudioStatus.PENDING.value,
        nullable=False,
    )
    visibility: Mapped[AudioVisibility] = mapped_column(
        SqlEnum(
            AudioVisibility,
            name="ck_audios_visibility",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=AudioVisibility.PRIVATE,
        server_default=AudioVisibility.PRIVATE.value,
        nullable=False,
    )
    audio_format: Mapped[str | None] = mapped_column(String(16))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    sample_width_bytes: Mapped[int | None] = mapped_column(Integer)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
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
    author: Mapped["User"] = relationship()
    utterances: Mapped[list["AudioUtterance"]] = relationship(
        back_populates="audio",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AudioUtterance.position",
    )
    tags: Mapped[list["AudioTag"]] = relationship(
        secondary=audio_tag_associations,
        order_by="AudioTag.id",
    )


class AudioUtterance(Base):
    __tablename__ = "audio_utterances"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_audio_utterances_position"),
        UniqueConstraint(
            "audio_id",
            "position",
            name="uq_audio_utterances_audio_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    audio_id: Mapped[int] = mapped_column(
        ForeignKey("audios.id", ondelete="CASCADE"),
        nullable=False,
    )
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "voices.id",
            name="fk_audio_utterances_voice_id_voices",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    speaker_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    audio: Mapped["Audio"] = relationship(back_populates="utterances")
    voice: Mapped["Voice"] = relationship()
