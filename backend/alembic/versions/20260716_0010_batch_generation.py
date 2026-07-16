"""Add generated batch content and speaker voice mappings.

Revision ID: 20260716_0010
Revises: 20260716_0009
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_batch_items",
        sa.Column("generated_content", sa.JSON(), nullable=True),
    )
    op.add_column(
        "generation_batch_items",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_table(
        "generation_batch_speaker_voices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=200), nullable=False),
        sa.Column("normalized_speaker", sa.String(length=200), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["generation_batches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "normalized_speaker",
            name="uq_generation_batch_speaker_voices_role",
        ),
    )


def downgrade() -> None:
    op.drop_table("generation_batch_speaker_voices")
    op.drop_column("generation_batch_items", "attempt_count")
    op.drop_column("generation_batch_items", "generated_content")
