"""Create corpus generation batches.

Revision ID: 20260716_0009
Revises: 20260716_0008
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    batch_status = (
        "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')"
    )
    op.create_table(
        "generation_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("question_types", sa.JSON(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
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
            "requested_count > 0",
            name="ck_generation_batches_count",
        ),
        sa.CheckConstraint(batch_status, name="ck_generation_batches_status"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(
        "ix_generation_batches_owner_created",
        "generation_batches",
        ["owner_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "generation_batch_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("audio_id", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
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
            "position >= 0",
            name="ck_generation_batch_items_position",
        ),
        sa.CheckConstraint(batch_status, name="ck_generation_batch_items_status"),
        sa.ForeignKeyConstraint(["audio_id"], ["audios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["generation_batches.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("audio_id", name="uq_generation_batch_items_audio_id"),
        sa.UniqueConstraint(
            "batch_id",
            "position",
            name="uq_generation_batch_items_batch_position",
        ),
    )
    op.create_table(
        "generation_batch_tag_associations",
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["generation_batches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["audio_tags.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("batch_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("generation_batch_tag_associations")
    op.drop_table("generation_batch_items")
    op.drop_index(
        "ix_generation_batches_owner_created",
        table_name="generation_batches",
    )
    op.drop_table("generation_batches")
