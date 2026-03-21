"""Add turn_timeout and turn_started_at columns to relays

Revision ID: 004
Revises: 003
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"


def upgrade():
    op.add_column("relays", sa.Column("turn_timeout", sa.Integer(), nullable=True))
    op.add_column("relays", sa.Column("turn_started_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("relays", "turn_started_at")
    op.drop_column("relays", "turn_timeout")
