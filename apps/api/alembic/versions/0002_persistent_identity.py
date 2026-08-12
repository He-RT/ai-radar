"""Persist identity roles and access sessions.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade both legacy 0001 databases and fresh installs.

    Revision 0001 builds from live metadata, so a fresh install using current
    code already contains these objects. The existence checks keep the forward
    migration safe in both cases without rewriting historical migration 0001.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" not in user_columns:
        op.add_column(
            "users",
            sa.Column("role", sa.String(length=32), server_default="user", nullable=False),
        )
        op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    if "identity_sessions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "identity_sessions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name=op.f("fk_identity_sessions_user_id_users"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_sessions")),
        )
        op.create_index(
            op.f("ix_identity_sessions_user_id"), "identity_sessions", ["user_id"], unique=False
        )
        op.create_index(
            op.f("ix_identity_sessions_token_hash"),
            "identity_sessions",
            ["token_hash"],
            unique=True,
        )
        op.create_index(
            op.f("ix_identity_sessions_expires_at"),
            "identity_sessions",
            ["expires_at"],
            unique=False,
        )
        op.create_index(
            op.f("ix_identity_sessions_revoked_at"),
            "identity_sessions",
            ["revoked_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("identity_sessions")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_column("users", "role")
