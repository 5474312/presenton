"""add encrypted MCP credential reveal

Revision ID: a7b9d1e3f5c8
Revises: f6a8c2e4b1d9
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a7b9d1e3f5c8"
down_revision: str | None = "f6a8c2e4b1d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("mcp_credentials")
    }
    if "token_encrypted" not in columns:
        op.add_column(
            "mcp_credentials",
            sa.Column("token_encrypted", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("mcp_credentials")
    }
    if "token_encrypted" in columns:
        op.drop_column("mcp_credentials", "token_encrypted")
