"""Add api_key_hash to relays

Revision ID: 002
Revises: 001
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"


def upgrade():
    op.add_column("relays", sa.Column("api_key_hash", sa.String(), nullable=True))


def downgrade():
    op.drop_column("relays", "api_key_hash")
