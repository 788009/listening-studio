"""Create users.

Revision ID: 20260716_0002
Revises: 20260716_0001
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0002"
down_revision: str | None = "20260716_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending_profile",
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("normalized_user_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column(
            "locale",
            sa.String(length=35),
            server_default="en",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending_profile', 'active')",
            name="ck_users_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_identity"),
        sa.UniqueConstraint(
            "normalized_user_id",
            name="uq_users_normalized_user_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
