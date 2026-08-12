"""Embed immutable public events in briefing snapshots.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the payload without fabricating history for existing rows.

    Revision 0001 creates live metadata, so a fresh database using current
    code already has this column. The existence check supports both that path
    and a real legacy 0002 database. Existing rows remain NULL and therefore
    fail closed at the repository boundary until an authoritative historical
    payload is supplied out of band.
    """

    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("briefing_snapshots")}
    if "event_snapshots" not in columns:
        op.add_column(
            "briefing_snapshots",
            sa.Column("event_snapshots", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    raise RuntimeError("0003 is forward-only: dropping immutable briefing history is unsafe")
