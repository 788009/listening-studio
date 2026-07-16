"""Establish the empty database baseline.

Revision ID: 20260716_0001
Revises: None
"""

from typing import Sequence


revision: str = "20260716_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
