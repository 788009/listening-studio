"""Add teacher account roles.

Revision ID: 20260721_0018
Revises: 20260720_0017
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_0018"
down_revision: str | None = "20260720_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_role_enum = sa.Enum(
    "user",
    "admin",
    "super_admin",
    name="ck_users_role",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "ALTER TABLE users ADD COLUMN role VARCHAR(32) "
            "DEFAULT 'user' NOT NULL CONSTRAINT ck_users_role "
            "CHECK (role IN ('user', 'admin', 'super_admin'))"
        )
        return
    op.add_column(
        "users",
        sa.Column(
            "role",
            _role_enum,
            server_default="user",
            nullable=False,
        )
    )


def downgrade() -> None:
    op.drop_column("users", "role")
