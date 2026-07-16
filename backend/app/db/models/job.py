from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.db.models.user import User


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress"),
        CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_jobs_result_reference",
        ),
        Index("ix_jobs_queue", "status", "cancel_requested", "id"),
        Index("ix_jobs_owner_created", "owner_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        SqlEnum(
            JobStatus,
            name="ck_jobs_status",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_type: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[int | None] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    owner: Mapped[User] = relationship()
