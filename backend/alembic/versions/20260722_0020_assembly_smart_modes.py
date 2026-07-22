"""Add assembly smart segment modes.

Revision ID: 20260722_0020
Revises: 20260722_0019
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0020"
down_revision: str | None = "20260722_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_smart_mode_enum = sa.Enum(
    "question_number",
    "question_count_silence",
    name="ck_assembly_template_segments_smart_mode",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    with op.batch_alter_table("assembly_template_segments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "smart_mode",
                _smart_mode_enum,
                server_default="question_number",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "smart_silence_previous",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "smart_silence_next",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("assembly_template_segments") as batch_op:
        batch_op.drop_constraint(
            "ck_assembly_template_segments_smart_mode",
            type_="check",
        )
        batch_op.drop_column("smart_silence_next")
        batch_op.drop_column("smart_silence_previous")
        batch_op.drop_column("smart_mode")
