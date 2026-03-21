"""Add agent_registrations table for cross-device discovery

Revision ID: 005
Revises: 004
"""
import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"


def upgrade():
    op.create_table(
        "agent_registrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("namespace", sa.String(), nullable=False, index=True),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=True),
        sa.Column("status", sa.String(), server_default="waiting"),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("agent_registrations")
