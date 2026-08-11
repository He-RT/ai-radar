"""Create the complete Radar schema.

Revision ID: 0001
Revises:
"""
from alembic import op
from zhenfu_api.persistence import tables  # noqa: F401
from zhenfu_api.persistence.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
