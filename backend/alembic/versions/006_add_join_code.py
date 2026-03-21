"""Add join_code column to relays table for cross-device discovery

Revision ID: 006
Revises: 005
"""
import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"


def upgrade():
    op.add_column(
        "relays",
        sa.Column("join_code", sa.String(6), nullable=True),
    )
    op.create_index("ix_relays_join_code", "relays", ["join_code"], unique=True)


def downgrade():
    op.drop_index("ix_relays_join_code", table_name="relays")
    op.drop_column("relays", "join_code")
