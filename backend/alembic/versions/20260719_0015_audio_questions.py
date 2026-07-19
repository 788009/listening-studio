"""Add audio questions and the system question tag.

Revision ID: 20260719_0015
Revises: 20260719_0014
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0015"
down_revision: str | None = "20260719_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CONSTRAINT_NAME = "ck_audio_tags_type"
_OLD_TYPES = "type IN ('author', 'voice', 'topic', 'category')"
_NEW_TYPES = "type IN ('author', 'voice', 'topic', 'category', 'other')"


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


def upgrade() -> None:
    _replace_type_constraint(_NEW_TYPES)
    op.create_table(
        "audio_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("audio_id", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_audio_questions_position"),
        sa.ForeignKeyConstraint(
            ["audio_id"],
            ["audios.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audio_id",
            "position",
            name="uq_audio_questions_audio_position",
        ),
    )
    op.create_table(
        "audio_question_answers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_audio_question_answers_position",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["audio_questions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id",
            "is_correct",
            "position",
            name="uq_audio_question_answers_kind_position",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    tags = sa.table(
        "audio_tags",
        sa.column("id", sa.Integer()),
        sa.column("type", sa.String(length=16)),
    )
    translations = sa.table(
        "audio_tag_translations",
        sa.column("tag_id", sa.Integer()),
    )
    associations = sa.table(
        "audio_tag_associations",
        sa.column("tag_id", sa.Integer()),
    )
    batch_associations = sa.table(
        "generation_batch_tag_associations",
        sa.column("tag_id", sa.Integer()),
    )
    other_ids = sa.select(tags.c.id).where(tags.c.type == "other")
    connection.execute(
        sa.delete(associations).where(associations.c.tag_id.in_(other_ids))
    )
    connection.execute(
        sa.delete(batch_associations).where(batch_associations.c.tag_id.in_(other_ids))
    )
    connection.execute(
        sa.delete(translations).where(translations.c.tag_id.in_(other_ids))
    )
    connection.execute(sa.delete(tags).where(tags.c.type == "other"))
    op.drop_table("audio_question_answers")
    op.drop_table("audio_questions")
    _replace_type_constraint(_OLD_TYPES)
