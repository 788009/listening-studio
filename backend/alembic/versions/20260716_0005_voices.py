"""Create voices and voice tag associations.

Revision ID: 20260716_0005
Revises: 20260716_0004
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0005"
down_revision: str | None = "20260716_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("normalized_title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "visibility",
            sa.String(length=16),
            server_default="private",
            nullable=False,
        ),
        sa.Column(
            "example_mode",
            sa.String(length=16),
            server_default="reference",
            nullable=False,
        ),
        sa.Column("example_audio_id", sa.Integer(), nullable=True),
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
            "(example_mode = 'reference' AND example_audio_id IS NULL) OR "
            "(example_mode = 'audio' AND example_audio_id IS NOT NULL)",
            name="ck_voices_example_source",
        ),
        sa.CheckConstraint(
            "example_mode IN ('reference', 'audio')",
            name="ck_voices_example_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_voices_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_voices_visibility",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voices_normalized_title",
        "voices",
        ["normalized_title"],
        unique=False,
    )
    op.create_table(
        "voice_tag_associations",
        sa.Column("voice_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["voice_tags.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("voice_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("voice_tag_associations")
    op.drop_index("ix_voices_normalized_title", table_name="voices")
    op.drop_table("voices")
