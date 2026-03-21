"""Add composite indexes for messages and webhooks

Revision ID: 003
Revises: 002
"""
from alembic import op

revision = "003"
down_revision = "002"


def upgrade():
    op.create_index(
        "ix_messages_relay_created",
        "messages",
        ["relay_id", "created_at"],
    )
    op.create_index(
        "ix_webhooks_relay_agent",
        "webhooks",
        ["relay_id", "agent_index"],
    )


def downgrade():
    op.drop_index("ix_webhooks_relay_agent", table_name="webhooks")
    op.drop_index("ix_messages_relay_created", table_name="messages")
