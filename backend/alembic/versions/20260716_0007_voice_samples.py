"""Rename and constrain voice sample sources.

Revision ID: 20260716_0007
Revises: 20260716_0006
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0007"
down_revision: str | None = "20260716_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("voices") as batch_op:
        batch_op.drop_constraint(
            "fk_voices_example_audio_id_audios",
            type_="foreignkey",
        )
        batch_op.drop_constraint("ck_voices_example_source", type_="check")
        batch_op.drop_constraint("ck_voices_example_mode", type_="check")
        batch_op.alter_column(
            "example_mode",
            new_column_name="sample_source",
            existing_type=sa.String(length=16),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "example_audio_id",
            new_column_name="sample_audio_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )

    op.execute(
        sa.text(
            "UPDATE voices SET sample_source = CASE sample_source "
            "WHEN 'reference' THEN 'original' "
            "WHEN 'audio' THEN 'public_audio' END"
        )
    )

    with op.batch_alter_table("voices") as batch_op:
        batch_op.alter_column(
            "sample_source",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default="original",
        )
        batch_op.create_check_constraint(
            "ck_voices_sample_source",
            "sample_source IN ('original', 'public_audio')",
        )
        batch_op.create_check_constraint(
            "ck_voices_sample_source_consistency",
            "(sample_source = 'original' AND sample_audio_id IS NULL) OR "
            "(sample_source = 'public_audio' AND sample_audio_id IS NOT NULL)",
        )
        batch_op.create_foreign_key(
            "fk_voices_sample_audio_id_audios",
            "audios",
            ["sample_audio_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("voices") as batch_op:
        batch_op.drop_constraint(
            "fk_voices_sample_audio_id_audios",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_voices_sample_source_consistency",
            type_="check",
        )
        batch_op.drop_constraint("ck_voices_sample_source", type_="check")
        batch_op.alter_column(
            "sample_source",
            new_column_name="example_mode",
            existing_type=sa.String(length=16),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "sample_audio_id",
            new_column_name="example_audio_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )

    op.execute(
        sa.text(
            "UPDATE voices SET example_mode = CASE example_mode "
            "WHEN 'original' THEN 'reference' "
            "WHEN 'public_audio' THEN 'audio' END"
        )
    )

    with op.batch_alter_table("voices") as batch_op:
        batch_op.alter_column(
            "example_mode",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default="reference",
        )
        batch_op.create_check_constraint(
            "ck_voices_example_mode",
            "example_mode IN ('reference', 'audio')",
        )
        batch_op.create_check_constraint(
            "ck_voices_example_source",
            "(example_mode = 'reference' AND example_audio_id IS NULL) OR "
            "(example_mode = 'audio' AND example_audio_id IS NOT NULL)",
        )
        batch_op.create_foreign_key(
            "fk_voices_example_audio_id_audios",
            "audios",
            ["example_audio_id"],
            ["id"],
            ondelete="RESTRICT",
        )
