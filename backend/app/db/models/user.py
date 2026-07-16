from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum
from sqlalchemy import String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class UserStatus(str, Enum):
    PENDING_PROFILE = "pending_profile"
    ACTIVE = "active"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_users_identity"),
        UniqueConstraint(
            "normalized_user_id",
            name="uq_users_normalized_user_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        SqlEnum(
            UserStatus,
            name="ck_users_status",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=UserStatus.PENDING_PROFILE,
        server_default=UserStatus.PENDING_PROFILE.value,
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(String(64))
    normalized_user_id: Mapped[str | None] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(200))
    locale: Mapped[str] = mapped_column(
        String(35),
        default="en",
        server_default="en",
        nullable=False,
    )
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

    @property
    def is_profile_complete(self) -> bool:
        return self.status is UserStatus.ACTIVE
