from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.db.models.audio import Audio
    from backend.app.db.models.audio_tag import AudioTag
    from backend.app.db.models.job import Job
    from backend.app.db.models.user import User


class GenerationBatchStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


generation_batch_tag_associations = Table(
    "generation_batch_tag_associations",
    Base.metadata,
    Column(
        "batch_id",
        ForeignKey("generation_batches.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("audio_tags.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class GenerationBatch(Base):
    __tablename__ = "generation_batches"
    __table_args__ = (
        CheckConstraint("requested_count > 0", name="ck_generation_batches_count"),
        Index(
            "ix_generation_batches_owner_created",
            "owner_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    question_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GenerationBatchStatus] = mapped_column(
        SqlEnum(
            GenerationBatchStatus,
            name="ck_generation_batches_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=GenerationBatchStatus.PENDING,
        server_default=GenerationBatchStatus.PENDING.value,
        nullable=False,
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
    job: Mapped["Job"] = relationship()
    tags: Mapped[list["AudioTag"]] = relationship(
        secondary=generation_batch_tag_associations,
        order_by="AudioTag.id",
    )
    items: Mapped[list["GenerationBatchItem"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenerationBatchItem.position",
    )


class GenerationBatchItem(Base):
    __tablename__ = "generation_batch_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_generation_batch_items_position"),
        UniqueConstraint(
            "batch_id",
            "position",
            name="uq_generation_batch_items_batch_position",
        ),
        UniqueConstraint("audio_id", name="uq_generation_batch_items_audio_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("generation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GenerationBatchStatus] = mapped_column(
        SqlEnum(
            GenerationBatchStatus,
            name="ck_generation_batch_items_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=GenerationBatchStatus.PENDING,
        server_default=GenerationBatchStatus.PENDING.value,
        nullable=False,
    )
    audio_id: Mapped[int | None] = mapped_column(
        ForeignKey("audios.id", ondelete="RESTRICT")
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
    batch: Mapped[GenerationBatch] = relationship(back_populates="items")
    audio: Mapped["Audio | None"] = relationship()
