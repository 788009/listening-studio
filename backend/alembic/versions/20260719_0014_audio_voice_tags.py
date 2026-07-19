"""Rename audio speaker tags to voice tags.

Revision ID: 20260719_0014
Revises: 20260719_0013
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0014"
down_revision: str | None = "20260719_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT_NAME = "ck_audio_tags_type"
_TRANSITION_TYPES = "type IN ('author', 'speaker', 'voice', 'topic', 'category')"
_VOICE_TYPES = "type IN ('author', 'voice', 'topic', 'category')"
_SPEAKER_TYPES = "type IN ('author', 'speaker', 'topic', 'category')"


def _dependent_tables() -> tuple[sa.TableClause, ...]:
    return (
        sa.table(
            "audio_tag_translations",
            sa.column("id", sa.Integer()),
            sa.column("tag_id", sa.Integer()),
            sa.column("language", sa.String(length=35)),
            sa.column("value", sa.String(length=255)),
            sa.column("normalized_value", sa.String(length=255)),
        ),
        sa.table(
            "audio_tag_associations",
            sa.column("audio_id", sa.Integer()),
            sa.column("tag_id", sa.Integer()),
        ),
        sa.table(
            "generation_batch_tag_associations",
            sa.column("batch_id", sa.Integer()),
            sa.column("tag_id", sa.Integer()),
        ),
    )


def _replace_type_constraint(expression: str) -> None:
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        op.drop_constraint(_CONSTRAINT_NAME, "audio_tags", type_="check")
        op.create_check_constraint(_CONSTRAINT_NAME, "audio_tags", expression)
        return

    dependent_rows: list[tuple[sa.TableClause, list[dict[str, object]]]] = []
    for table in _dependent_tables():
        rows = [dict(row._mapping) for row in connection.execute(sa.select(table))]
        dependent_rows.append((table, rows))
        connection.execute(sa.delete(table))

    with op.batch_alter_table("audio_tags", recreate="always") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(_CONSTRAINT_NAME, expression)

    for table, rows in dependent_rows:
        if rows:
            connection.execute(sa.insert(table), rows)


def _rename_type(old: str, new: str) -> None:
    audio_tags = sa.table("audio_tags", sa.column("type", sa.String(length=16)))
    op.execute(
        sa.update(audio_tags)
        .where(audio_tags.c.type == old)
        .values(type=new)
    )


def upgrade() -> None:
    _replace_type_constraint(_TRANSITION_TYPES)
    _rename_type("speaker", "voice")
    _replace_type_constraint(_VOICE_TYPES)


def downgrade() -> None:
    _replace_type_constraint(_TRANSITION_TYPES)
    _rename_type("voice", "speaker")
    _replace_type_constraint(_SPEAKER_TYPES)
