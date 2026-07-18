"""Preserve audio utterances after voice deletion.

Revision ID: 20260718_0012
Revises: 20260716_0011
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0012"
down_revision: str | None = "20260716_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_VOICE_FOREIGN_KEY = "fk_audio_utterances_voice_id_voices"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE audio_utterances "
            "SET speaker_display_name = ("
            "SELECT voices.title FROM voices "
            "WHERE voices.id = audio_utterances.voice_id"
            ") "
            "WHERE voice_id IS NOT NULL "
            "AND audio_id IN ("
            "SELECT id FROM audios WHERE source_type = 'single_speaker'"
            ")"
        )
    )
    with op.batch_alter_table(
        "audio_utterances",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(_VOICE_FOREIGN_KEY, type_="foreignkey")
        batch_op.alter_column(
            "voice_id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.create_foreign_key(
            _VOICE_FOREIGN_KEY,
            "voices",
            ["voice_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    orphaned_utterances = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM audio_utterances WHERE voice_id IS NULL")
    )
    if orphaned_utterances:
        raise RuntimeError(
            "Cannot downgrade while deleted-voice utterance history exists"
        )
    with op.batch_alter_table(
        "audio_utterances",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(_VOICE_FOREIGN_KEY, type_="foreignkey")
        batch_op.alter_column(
            "voice_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.create_foreign_key(
            _VOICE_FOREIGN_KEY,
            "voices",
            ["voice_id"],
            ["id"],
            ondelete="RESTRICT",
        )
