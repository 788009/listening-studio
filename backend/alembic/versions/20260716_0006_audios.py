"""Create audios, utterances, and audio tag associations.

Revision ID: 20260716_0006
Revises: 20260716_0005
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0006"
down_revision: str | None = "20260716_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audios",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("normalized_title", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "visibility",
            sa.String(length=16),
            server_default="private",
            nullable=False,
        ),
        sa.Column("audio_format", sa.String(length=16), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("sample_width_bytes", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
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
        sa.CheckConstraint(
            "source_type IN "
            "('single_speaker', 'multi_turn', 'corpus', 'assembly')",
            name="ck_audios_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_audios_status",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_audios_visibility",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audios_normalized_title",
        "audios",
        ["normalized_title"],
        unique=False,
    )
    op.create_table(
        "audio_tag_associations",
        sa.Column("audio_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["audio_id"],
            ["audios.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["audio_tags.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("audio_id", "tag_id"),
    )
    op.create_table(
        "audio_utterances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("audio_id", sa.Integer(), nullable=False),
        sa.Column("voice_id", sa.Integer(), nullable=False),
        sa.Column("speaker_display_name", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_audio_utterances_position",
        ),
        sa.ForeignKeyConstraint(
            ["audio_id"],
            ["audios.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voice_id"],
            ["voices.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audio_id",
            "position",
            name="uq_audio_utterances_audio_position",
        ),
    )
    with op.batch_alter_table("voices") as batch_op:
        batch_op.create_foreign_key(
            "fk_voices_example_audio_id_audios",
            "audios",
            ["example_audio_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("voices") as batch_op:
        batch_op.drop_constraint(
            "fk_voices_example_audio_id_audios",
            type_="foreignkey",
        )
    op.drop_table("audio_utterances")
    op.drop_table("audio_tag_associations")
    op.drop_index("ix_audios_normalized_title", table_name="audios")
    op.drop_table("audios")
