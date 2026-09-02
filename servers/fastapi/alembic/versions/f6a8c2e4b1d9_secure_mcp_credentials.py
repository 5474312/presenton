"""add secure user-scoped MCP credentials

Revision ID: f6a8c2e4b1d9
Revises: e4c7a9b2d6f1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f6a8c2e4b1d9"
down_revision: str | None = "e4c7a9b2d6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "mcp_credentials" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "mcp_credentials",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("secret_hash", sa.String(length=512), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "created_by_id", "expires_at", "revoked_at"):
        op.create_index(f"ix_mcp_credentials_{column}", "mcp_credentials", [column])


def downgrade() -> None:
    if "mcp_credentials" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("mcp_credentials")
