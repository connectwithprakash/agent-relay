"""Add agent_presence table for heartbeat/liveness tracking

Revision ID: 009
Revises: 008
"""
import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"


def upgrade():
    op.create_table(
        "agent_presence",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("relay_id", sa.String, sa.ForeignKey("relays.id"), nullable=False),
        sa.Column("agent_name", sa.String, nullable=False),
        sa.Column("last_seen", sa.DateTime, nullable=True),
        sa.Column("status", sa.String, default="active"),
    )
    op.create_index(
        "ix_agent_presence_relay_agent",
        "agent_presence",
        ["relay_id", "agent_name"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_agent_presence_relay_agent", table_name="agent_presence")
    op.drop_table("agent_presence")
