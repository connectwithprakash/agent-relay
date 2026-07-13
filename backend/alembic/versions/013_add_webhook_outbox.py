"""Add durable webhook transactional outbox.

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("webhook_outbox"):
        required_columns = {
            "id", "webhook_id", "message_id", "relay_id", "target_url",
            "payload", "status", "attempts", "next_attempt_at", "locked_at",
            "lock_token", "last_error", "created_at", "delivered_at",
        }
        actual_columns = {column["name"] for column in inspector.get_columns("webhook_outbox")}
        required_indexes = {"ix_webhook_outbox_due", "ix_webhook_outbox_lock"}
        actual_indexes = {index["name"] for index in inspector.get_indexes("webhook_outbox")}
        if not required_columns.issubset(actual_columns) or not required_indexes.issubset(actual_indexes):
            raise RuntimeError("Existing webhook_outbox table does not match revision 013")
        return
    op.create_table(
        "webhook_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("relay_id", sa.String(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("lock_token", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "webhook_id", "message_id", name="uq_webhook_outbox_event"
        ),
    )
    op.create_index(
        "ix_webhook_outbox_due",
        "webhook_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_webhook_outbox_lock",
        "webhook_outbox",
        ["status", "locked_at"],
    )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("webhook_outbox"):
        op.drop_index("ix_webhook_outbox_lock", table_name="webhook_outbox")
        op.drop_index("ix_webhook_outbox_due", table_name="webhook_outbox")
        op.drop_table("webhook_outbox")
