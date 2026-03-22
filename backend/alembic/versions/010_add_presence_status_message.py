"""Add status_message column to agent_presence for activity descriptions

Revision ID: 010
Revises: 009
"""
import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"


def upgrade():
    op.add_column(
        "agent_presence",
        sa.Column("status_message", sa.String(200), nullable=True),
    )


def downgrade():
    op.drop_column("agent_presence", "status_message")
