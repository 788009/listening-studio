from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.db.models.user import User
    from backend.app.db.models.voice_tag import VoiceTag


class VoiceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class VoiceVisibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


class VoiceExampleMode(str, Enum):
    REFERENCE = "reference"
    AUDIO = "audio"


voice_tag_associations = Table(
    "voice_tag_associations",
    Base.metadata,
    Column(
        "voice_id",
        ForeignKey("voices.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("voice_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Voice(Base):
    __tablename__ = "voices"
    __table_args__ = (
        CheckConstraint(
            "(example_mode = 'reference' AND example_audio_id IS NULL) OR "
            "(example_mode = 'audio' AND example_audio_id IS NOT NULL)",
            name="ck_voices_example_source",
        ),
        Index("ix_voices_normalized_title", "normalized_title"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[VoiceStatus] = mapped_column(
        SqlEnum(
            VoiceStatus,
            name="ck_voices_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=VoiceStatus.PENDING,
        server_default=VoiceStatus.PENDING.value,
        nullable=False,
    )
    visibility: Mapped[VoiceVisibility] = mapped_column(
        SqlEnum(
            VoiceVisibility,
            name="ck_voices_visibility",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=VoiceVisibility.PRIVATE,
        server_default=VoiceVisibility.PRIVATE.value,
        nullable=False,
    )
    example_mode: Mapped[VoiceExampleMode] = mapped_column(
        SqlEnum(
            VoiceExampleMode,
            name="ck_voices_example_mode",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=VoiceExampleMode.REFERENCE,
        server_default=VoiceExampleMode.REFERENCE.value,
        nullable=False,
    )
    # E01 adds the foreign key after the audio table exists.
    example_audio_id: Mapped[int | None] = mapped_column(Integer)
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
    tags: Mapped[list["VoiceTag"]] = relationship(
        secondary=voice_tag_associations,
        order_by="VoiceTag.id",
    )
