"""Create persistent jobs.

Revision ID: 20260716_0008
Revises: 20260716_0007
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0008"
down_revision: str | None = "20260716_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("result_type", sa.String(length=64), nullable=True),
        sa.Column("result_id", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "retryable",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "progress >= 0 AND progress <= 100",
            name="ck_jobs_progress",
        ),
        sa.CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL)",
            name="ck_jobs_result_reference",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jobs_owner_created",
        "jobs",
        ["owner_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_queue",
        "jobs",
        ["status", "cancel_requested", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_queue", table_name="jobs")
    op.drop_index("ix_jobs_owner_created", table_name="jobs")
    op.drop_table("jobs")
