"""replace legacy and MCP credentials with unified API keys

Revision ID: b9d3e5f7a1c2
Revises: a7b9d1e3f5c8
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b9d3e5f7a1c2"
down_revision: str | None = "a7b9d1e3f5c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "api_keys" not in tables:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("secret_hash", sa.String(length=512), nullable=False),
            sa.Column("token_encrypted", sa.String(length=1024), nullable=True),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("created_by_id", sa.Uuid(), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["created_by_id"], ["user.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("user_id", "created_by_id", "expires_at", "revoked_at"):
            op.create_index(f"ix_api_keys_{column}", "api_keys", [column])

    # These credentials use incompatible token formats and are intentionally
    # not migrated. This release supports only the unified sk-presenton key.
    if "mcp_credentials" in tables:
        op.drop_table("mcp_credentials")
    if "access_tokens" in tables:
        op.drop_table("access_tokens")


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "access_tokens" not in tables:
        op.create_table(
            "access_tokens",
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("token"),
        )
        op.create_index("ix_access_tokens_token", "access_tokens", ["token"])
        op.create_index("ix_access_tokens_user_id", "access_tokens", ["user_id"])

    if "mcp_credentials" not in tables:
        op.create_table(
            "mcp_credentials",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("secret_hash", sa.String(length=512), nullable=False),
            sa.Column("token_encrypted", sa.String(length=1024), nullable=True),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("created_by_id", sa.Uuid(), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["created_by_id"], ["user.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("user_id", "created_by_id", "expires_at", "revoked_at"):
            op.create_index(
                f"ix_mcp_credentials_{column}", "mcp_credentials", [column]
            )

    if "api_keys" in tables:
        op.drop_table("api_keys")
