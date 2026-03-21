"""Add description, capabilities, and metadata columns to agent_registrations

Revision ID: 007
Revises: 006
"""
import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"


def upgrade():
    op.add_column(
        "agent_registrations",
        sa.Column("description", sa.String(), nullable=True),
    )
    op.add_column(
        "agent_registrations",
        sa.Column("capabilities", sa.JSON(), nullable=True),
    )
    op.add_column(
        "agent_registrations",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("agent_registrations", "metadata")
    op.drop_column("agent_registrations", "capabilities")
    op.drop_column("agent_registrations", "description")
