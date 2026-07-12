"""Add reply_to and message_type columns to messages for threading and categorization

Revision ID: 008
Revises: 007
"""
import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"


def upgrade():
    # SQLite cannot add a foreign-key constraint through ALTER TABLE. Batch
    # mode performs the portable copy-and-swap migration.
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("reply_to", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("message_type", sa.String(), server_default="text", nullable=False))
        batch.create_foreign_key("fk_messages_reply_to", "messages", ["reply_to"], ["id"])


def downgrade():
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("fk_messages_reply_to", type_="foreignkey")
        batch.drop_column("message_type")
        batch.drop_column("reply_to")
