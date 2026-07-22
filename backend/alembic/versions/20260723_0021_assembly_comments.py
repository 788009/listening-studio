"""Add assembly comment segments.

Revision ID: 20260723_0021
Revises: 20260722_0020
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0021"
down_revision: str | None = "20260722_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TYPE_CONSTRAINT = "ck_assembly_template_segments_type"
_OLD_TYPES = "type IN ('audio', 'silence', 'placeholder', 'smart')"
_NEW_TYPES = "type IN ('audio', 'silence', 'placeholder', 'smart', 'comment')"


def upgrade() -> None:
    with op.batch_alter_table("assembly_template_segments") as batch_op:
        batch_op.drop_constraint(_TYPE_CONSTRAINT, type_="check")
        batch_op.add_column(sa.Column("comment_text", sa.Text(), nullable=True))
        batch_op.create_check_constraint(_TYPE_CONSTRAINT, _NEW_TYPES)


def downgrade() -> None:
    segments = sa.table(
        "assembly_template_segments",
        sa.column("type", sa.String()),
    )
    op.get_bind().execute(sa.delete(segments).where(segments.c.type == "comment"))
    with op.batch_alter_table("assembly_template_segments") as batch_op:
        batch_op.drop_constraint(_TYPE_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(_TYPE_CONSTRAINT, _OLD_TYPES)
        batch_op.drop_column("comment_text")
