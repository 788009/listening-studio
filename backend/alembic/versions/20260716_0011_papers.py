"""Create paper presets, papers, and ordered items.

Revision ID: 20260716_0011
Revises: 20260716_0010
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0011"
down_revision: str | None = "20260716_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timing_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            "intro_silence_milliseconds >= 0 AND "
            "intro_silence_milliseconds <= 60000",
            name=f"ck_{prefix}_intro_silence",
        ),
        sa.CheckConstraint(
            "inter_item_silence_milliseconds >= 0 AND "
            "inter_item_silence_milliseconds <= 60000",
            name=f"ck_{prefix}_inter_item_silence",
        ),
        sa.CheckConstraint(
            "repeat_count >= 1 AND repeat_count <= 10",
            name=f"ck_{prefix}_repeat_count",
        ),
        sa.CheckConstraint(
            "outro_silence_milliseconds >= 0 AND "
            "outro_silence_milliseconds <= 60000",
            name=f"ck_{prefix}_outro_silence",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "paper_presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("intro_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column("inter_item_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("outro_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *_timing_constraints("paper_presets"),
        sa.CheckConstraint(
            "(is_builtin AND owner_id IS NULL) OR "
            "(NOT is_builtin AND owner_id IS NOT NULL)",
            name="ck_paper_presets_ownership",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_paper_presets_owner",
        "paper_presets",
        ["owner_id", "id"],
        unique=False,
    )
    preset_table = sa.table(
        "paper_presets",
        sa.column("name", sa.String()),
        sa.column("is_builtin", sa.Boolean()),
        sa.column("intro_silence_milliseconds", sa.Integer()),
        sa.column("inter_item_silence_milliseconds", sa.Integer()),
        sa.column("repeat_count", sa.Integer()),
        sa.column("outro_silence_milliseconds", sa.Integer()),
    )
    op.bulk_insert(
        preset_table,
        [
            {
                "name": "Standard",
                "is_builtin": True,
                "intro_silence_milliseconds": 1000,
                "inter_item_silence_milliseconds": 3000,
                "repeat_count": 1,
                "outro_silence_milliseconds": 1000,
            },
            {
                "name": "Review",
                "is_builtin": True,
                "intro_silence_milliseconds": 1000,
                "inter_item_silence_milliseconds": 5000,
                "repeat_count": 2,
                "outro_silence_milliseconds": 1000,
            },
        ],
    )
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("preset_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("normalized_title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("intro_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column("inter_item_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False),
        sa.Column("outro_silence_milliseconds", sa.Integer(), nullable=False),
        sa.Column("result_audio_id", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        *_timing_constraints("papers"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_papers_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["preset_id"],
            ["paper_presets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_audio_id"],
            ["audios.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_audio_id"),
    )
    op.create_index(
        "ix_papers_owner_created",
        "papers",
        ["owner_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "paper_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("audio_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_paper_items_position"),
        sa.ForeignKeyConstraint(["audio_id"], ["audios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "paper_id",
            "position",
            name="uq_paper_items_paper_position",
        ),
    )


def downgrade() -> None:
    op.drop_table("paper_items")
    op.drop_index("ix_papers_owner_created", table_name="papers")
    op.drop_table("papers")
    op.drop_index("ix_paper_presets_owner", table_name="paper_presets")
    op.drop_table("paper_presets")
