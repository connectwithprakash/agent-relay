"""Add reply_to and message_type columns to messages for threading and categorization

Revision ID: 008
Revises: 007
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"


def upgrade():
    op.add_column(
        "messages",
        sa.Column("reply_to", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("message_type", sa.String(), server_default="text", nullable=False),
    )


def downgrade():
    op.drop_column("messages", "message_type")
    op.drop_column("messages", "reply_to")
