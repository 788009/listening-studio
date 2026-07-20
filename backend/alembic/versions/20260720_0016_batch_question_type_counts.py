"""Store a count for each generation batch question type.

Revision ID: 20260720_0016
Revises: 20260719_0015
"""

from collections.abc import Sequence
import json

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0016"
down_revision: str | None = "20260719_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN_TYPES = {"short_dialogue", "long_dialogue", "monologue"}


def upgrade() -> None:
    connection = op.get_bind()
    legacy = sa.table(
        "generation_batches",
        sa.column("id", sa.Integer()),
        sa.column("question_types", sa.JSON()),
        sa.column("requested_count", sa.Integer()),
    )
    legacy_rows = [
        (
            row["id"],
            _legacy_counts(row["question_types"], row["requested_count"]),
        )
        for row in connection.execute(
            sa.select(legacy.c.id, legacy.c.question_types, legacy.c.requested_count)
        ).mappings()
    ]

    with op.batch_alter_table("generation_batches") as batch_op:
        batch_op.drop_constraint("ck_generation_batches_count", type_="check")
        batch_op.drop_column("question_types")
        batch_op.drop_column("requested_count")

    op.create_table(
        "generation_batch_question_types",
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "question_type IN ('short_dialogue', 'long_dialogue', 'monologue')",
            name="ck_generation_batch_question_types_type",
        ),
        sa.CheckConstraint(
            "requested_count > 0",
            name="ck_generation_batch_question_types_count",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_generation_batch_question_types_position",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["generation_batches.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("batch_id", "question_type"),
        sa.UniqueConstraint(
            "batch_id",
            "position",
            name="uq_generation_batch_question_types_position",
        ),
    )

    requests = sa.table(
        "generation_batch_question_types",
        sa.column("batch_id", sa.Integer()),
        sa.column("question_type", sa.String()),
        sa.column("requested_count", sa.Integer()),
        sa.column("position", sa.Integer()),
    )
    for batch_id, values in legacy_rows:
        if values:
            connection.execute(
                requests.insert(),
                [
                    {
                        "batch_id": batch_id,
                        "question_type": question_type,
                        "requested_count": count,
                        "position": position,
                    }
                    for position, (question_type, count) in enumerate(values)
                ],
            )

def downgrade() -> None:
    connection = op.get_bind()
    requests = sa.table(
        "generation_batch_question_types",
        sa.column("batch_id", sa.Integer()),
        sa.column("question_type", sa.String()),
        sa.column("requested_count", sa.Integer()),
        sa.column("position", sa.Integer()),
    )
    request_rows: dict[int, list[tuple[str, int]]] = {}
    for row in connection.execute(
        sa.select(
            requests.c.batch_id,
            requests.c.question_type,
            requests.c.requested_count,
        ).order_by(requests.c.batch_id, requests.c.position)
    ):
        request_rows.setdefault(row.batch_id, []).append(
            (row.question_type, row.requested_count)
        )

    with op.batch_alter_table("generation_batches") as batch_op:
        batch_op.add_column(sa.Column("question_types", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("requested_count", sa.Integer(), nullable=True))

    batches = sa.table(
        "generation_batches",
        sa.column("id", sa.Integer()),
        sa.column("question_types", sa.JSON()),
        sa.column("requested_count", sa.Integer()),
    )
    batch_ids = connection.execute(sa.select(batches.c.id)).scalars()
    for batch_id in batch_ids:
        rows = request_rows.get(batch_id, [("short_dialogue", 1)])
        connection.execute(
            batches.update()
            .where(batches.c.id == batch_id)
            .values(
                question_types=[question_type for question_type, _ in rows],
                requested_count=sum(count for _, count in rows),
            )
        )

    with op.batch_alter_table("generation_batches") as batch_op:
        batch_op.alter_column("question_types", nullable=False)
        batch_op.alter_column("requested_count", nullable=False)
        batch_op.create_check_constraint(
            "ck_generation_batches_count",
            "requested_count > 0",
        )
    op.drop_table("generation_batch_question_types")


def _legacy_counts(raw_types: object, raw_total: object) -> list[tuple[str, int]]:
    if isinstance(raw_types, str):
        try:
            raw_types = json.loads(raw_types)
        except ValueError:
            raw_types = []
    question_types = raw_types if isinstance(raw_types, list) else []
    normalized = [
        value if isinstance(value, str) and value in _KNOWN_TYPES else "short_dialogue"
        for value in question_types
    ]
    unique_types = list(dict.fromkeys(normalized)) or ["short_dialogue"]
    total = raw_total if isinstance(raw_total, int) and raw_total > 0 else len(unique_types)
    counts = {question_type: 0 for question_type in unique_types}
    for position in range(max(total, len(unique_types))):
        counts[unique_types[position % len(unique_types)]] += 1
    return list(counts.items())
