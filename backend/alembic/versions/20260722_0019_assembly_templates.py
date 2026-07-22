"""Add assembly templates and the full paper category.

Revision ID: 20260722_0019
Revises: 20260721_0018
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0019"
down_revision: str | None = "20260721_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_tables = set(sa.inspect(connection).get_table_names())
    if "assembly_templates" not in existing_tables:
        op.create_table(
            "assembly_templates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("normalized_title", sa.String(length=200), nullable=False),
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
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "normalized_title", name="uq_assembly_templates_normalized_title"
            ),
        )
        op.create_index(
            "ix_assembly_templates_created", "assembly_templates", ["created_at", "id"]
        )
    if "assembly_template_segments" not in existing_tables:
        op.create_table(
            "assembly_template_segments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("template_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=16), nullable=False),
            sa.Column("audio_id", sa.Integer()),
            sa.Column("suggested_query", sa.String(length=1024)),
            sa.Column(
                "silence_milliseconds", sa.Integer(), server_default="0", nullable=False
            ),
            sa.Column("repeat_count", sa.Integer(), server_default="1", nullable=False),
            sa.Column(
                "repeat_interval_milliseconds",
                sa.Integer(),
                server_default="0",
                nullable=False,
            ),
            sa.Column(
                "include_text", sa.Boolean(), server_default=sa.true(), nullable=False
            ),
            sa.Column(
                "include_topic", sa.Boolean(), server_default=sa.true(), nullable=False
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "position >= 0", name="ck_assembly_template_segments_position"
            ),
            sa.CheckConstraint(
                "repeat_count >= 1 AND repeat_count <= 10",
                name="ck_assembly_template_segments_repeat_count",
            ),
            sa.CheckConstraint(
                "repeat_interval_milliseconds >= 0 AND repeat_interval_milliseconds <= 60000",
                name="ck_assembly_template_segments_repeat_interval",
            ),
            sa.CheckConstraint(
                "silence_milliseconds >= 0 AND silence_milliseconds <= 60000",
                name="ck_assembly_template_segments_silence",
            ),
            sa.CheckConstraint(
                "type IN ('audio', 'silence', 'placeholder', 'smart')",
                name="ck_assembly_template_segments_type",
            ),
            sa.ForeignKeyConstraint(
                ["template_id"], ["assembly_templates.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["audio_id"], ["audios.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "template_id",
                "position",
                name="uq_assembly_template_segments_template_position",
            ),
        )
    tags = sa.table(
        "audio_tags",
        sa.column("id", sa.Integer()),
        sa.column("type", sa.String()),
        sa.column("value", sa.String()),
        sa.column("normalized_value", sa.String()),
    )
    translations = sa.table(
        "audio_tag_translations",
        sa.column("tag_id", sa.Integer()),
        sa.column("language", sa.String()),
        sa.column("value", sa.String()),
        sa.column("normalized_value", sa.String()),
    )
    tag_id = connection.scalar(
        sa.select(tags.c.id).where(
            tags.c.type == "category", tags.c.normalized_value == "full_paper"
        )
    )
    if tag_id is None:
        connection.execute(
            sa.insert(tags).values(
                type="category", value="full_paper", normalized_value="full_paper"
            )
        )
        tag_id = connection.scalar(
            sa.select(tags.c.id).where(
                tags.c.type == "category", tags.c.normalized_value == "full_paper"
            )
        )
    assert tag_id is not None
    if (
        connection.scalar(
            sa.select(translations.c.tag_id).where(
                translations.c.tag_id == tag_id, translations.c.language == "zh-CN"
            )
        )
        is None
    ):
        connection.execute(
            sa.insert(translations).values(
                tag_id=tag_id, language="zh-CN", value="套卷", normalized_value="套卷"
            )
        )


def downgrade() -> None:
    op.drop_table("assembly_template_segments")
    op.drop_index("ix_assembly_templates_created", table_name="assembly_templates")
    op.drop_table("assembly_templates")
