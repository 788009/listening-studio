"""Make audio and voice titles globally unique.

Revision ID: 20260719_0013
Revises: 20260718_0012
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0013"
down_revision: str | None = "20260718_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_unique_titles(table_name: str) -> None:
    resource_table = sa.table(
        table_name,
        sa.column("normalized_title", sa.String(length=200)),
    )
    duplicate = op.get_bind().execute(
        sa.select(resource_table.c.normalized_title)
        .group_by(resource_table.c.normalized_title)
        .having(sa.func.count() > 1)
        .limit(1)
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot enforce global title uniqueness for {table_name}: "
            f"duplicate normalized title {duplicate[0]!r}"
        )


def upgrade() -> None:
    for table_name in ("audios", "voices"):
        _require_unique_titles(table_name)
        index_name = f"ix_{table_name}_normalized_title"
        op.drop_index(index_name, table_name=table_name)
        op.create_index(
            index_name,
            table_name,
            ["normalized_title"],
            unique=True,
        )


def downgrade() -> None:
    for table_name in ("audios", "voices"):
        index_name = f"ix_{table_name}_normalized_title"
        op.drop_index(index_name, table_name=table_name)
        op.create_index(
            index_name,
            table_name,
            ["normalized_title"],
            unique=False,
        )
