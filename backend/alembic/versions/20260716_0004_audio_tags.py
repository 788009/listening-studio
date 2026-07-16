"""Create audio tags and translations.

Revision ID: 20260716_0004
Revises: 20260716_0003
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0004"
down_revision: str | None = "20260716_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audio_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("normalized_value", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "type IN ('author', 'speaker', 'topic', 'category')",
            name="ck_audio_tags_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "type",
            "normalized_value",
            name="uq_audio_tags_type_normalized_value",
        ),
    )
    op.create_table(
        "audio_tag_translations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=35), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("normalized_value", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["audio_tags.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tag_id",
            "language",
            name="uq_audio_tag_translations_tag_language",
        ),
    )


def downgrade() -> None:
    op.drop_table("audio_tag_translations")
    op.drop_table("audio_tags")
