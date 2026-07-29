"""Allow terminal generation batches to release deleted voices.

Revision ID: 20260729_0023
Revises: 20260723_0022
"""

from typing import Sequence

from alembic import op


revision: str = "20260729_0023"
down_revision: str | None = "20260723_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_VOICE_FOREIGN_KEY = "fk_generation_batch_speaker_voices_voice_id_voices"


def upgrade() -> None:
    with op.batch_alter_table(
        "generation_batch_speaker_voices",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(_VOICE_FOREIGN_KEY, type_="foreignkey")
        batch_op.create_foreign_key(
            _VOICE_FOREIGN_KEY,
            "voices",
            ["voice_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "generation_batch_speaker_voices",
        recreate="always",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(_VOICE_FOREIGN_KEY, type_="foreignkey")
        batch_op.create_foreign_key(
            _VOICE_FOREIGN_KEY,
            "voices",
            ["voice_id"],
            ["id"],
            ondelete="RESTRICT",
        )
