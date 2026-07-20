"""Backfill localized question type category tags.

Revision ID: 20260720_0017
Revises: 20260720_0016
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_0017"
down_revision: str | None = "20260720_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CATEGORY_TRANSLATIONS = (
    ("short", "短对话"),
    ("long", "长对话"),
    ("monologue", "独白"),
)


def upgrade() -> None:
    connection = op.get_bind()
    tags = sa.table(
        "audio_tags",
        sa.column("id", sa.Integer()),
        sa.column("type", sa.String(length=16)),
        sa.column("value", sa.String(length=255)),
        sa.column("normalized_value", sa.String(length=255)),
    )
    translations = sa.table(
        "audio_tag_translations",
        sa.column("tag_id", sa.Integer()),
        sa.column("language", sa.String(length=35)),
        sa.column("value", sa.String(length=255)),
        sa.column("normalized_value", sa.String(length=255)),
    )

    for english_value, chinese_value in _CATEGORY_TRANSLATIONS:
        tag_id = connection.scalar(
            sa.select(tags.c.id).where(
                tags.c.type == "category",
                tags.c.normalized_value == english_value,
            )
        )
        if tag_id is None:
            continue
        translation_id = connection.scalar(
            sa.select(translations.c.tag_id).where(
                translations.c.tag_id == tag_id,
                translations.c.language == "zh-CN",
            )
        )
        if translation_id is None:
            connection.execute(
                sa.insert(translations).values(
                    tag_id=tag_id,
                    language="zh-CN",
                    value=chinese_value,
                    normalized_value=chinese_value.casefold(),
                )
            )


def downgrade() -> None:
    # Preserve localized business data that may already be in use.
    pass
