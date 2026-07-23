"""Allow audio transcript lines without a speaker.

Revision ID: 20260723_0022
Revises: 20260723_0021
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0022"
down_revision: str | None = "20260723_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("audio_utterances") as batch_op:
        batch_op.alter_column(
            "speaker_display_name",
            existing_type=sa.String(length=200),
            nullable=True,
        )


def downgrade() -> None:
    utterances = sa.table(
        "audio_utterances",
        sa.column("speaker_display_name", sa.String(length=200)),
    )
    op.get_bind().execute(
        sa.delete(utterances).where(utterances.c.speaker_display_name.is_(None))
    )
    with op.batch_alter_table("audio_utterances") as batch_op:
        batch_op.alter_column(
            "speaker_display_name",
            existing_type=sa.String(length=200),
            nullable=False,
        )
