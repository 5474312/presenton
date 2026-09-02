"""add private payload to async tasks

Revision ID: f5b8d1c3a7e9
Revises: a7b9d1e3f5c8
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f5b8d1c3a7e9"
down_revision: str | None = "a7b9d1e3f5c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if not _has_table("async_tasks") or _has_column("async_tasks", "payload"):
        return
    op.add_column("async_tasks", sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_table("async_tasks") and _has_column("async_tasks", "payload"):
        op.drop_column("async_tasks", "payload")
