"""Reliable relay core schema
Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa
revision = "011"
down_revision = "010"
def upgrade():
    bind = op.get_bind()
    relay_columns = {column["name"] for column in sa.inspect(bind).get_columns("relays")}
    for name, column in (
        ("version", sa.Column("version", sa.Integer(), nullable=False, server_default="0")),
        ("description", sa.Column("description", sa.Text(), nullable=True)),
        ("agent_instructions", sa.Column("agent_instructions", sa.JSON(), nullable=True)),
        ("max_agents", sa.Column("max_agents", sa.Integer(), nullable=False, server_default="10")),
        ("min_agents", sa.Column("min_agents", sa.Integer(), nullable=False, server_default="2")),
        ("turns_waited", sa.Column("turns_waited", sa.JSON(), nullable=True)),
        ("max_skip_count", sa.Column("max_skip_count", sa.Integer(), nullable=False, server_default="3")),
    ):
        if name not in relay_columns:
            op.add_column("relays", column)
    message_columns = {column["name"] for column in sa.inspect(bind).get_columns("messages")}
    if "idempotency_key" not in message_columns:
        op.add_column("messages", sa.Column("idempotency_key", sa.String(255), nullable=True))
    if "agent_tokens" not in sa.inspect(bind).get_table_names():
        op.create_table("agent_tokens", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("token_prefix", sa.String(16), nullable=False), sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False), sa.Column("agent_name", sa.String(), nullable=False), sa.Column("is_creator", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(), nullable=False))
    else:
        op.add_column("agent_tokens", sa.Column("token_hash", sa.String(64), nullable=True))
        op.add_column("agent_tokens", sa.Column("token_prefix", sa.String(16), nullable=True))
    op.create_index("ix_agent_tokens_token_hash", "agent_tokens", ["token_hash"], unique=True)
    op.create_index("ix_agent_tokens_token_prefix", "agent_tokens", ["token_prefix"])
    op.create_table("pairing_invitations", sa.Column("id", sa.String(), primary_key=True), sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False), sa.Column("agent_name", sa.String(), nullable=False), sa.Column("secret_hash", sa.String(64), nullable=False, unique=True), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("redeemed_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.UniqueConstraint("relay_id", "agent_name", name="uq_pairing_invitation_relay_agent"))
    op.create_index("ix_pairing_invitations_relay_id", "pairing_invitations", ["relay_id"])
    with op.batch_alter_table("messages") as batch: batch.create_unique_constraint("uq_messages_relay_agent_idempotency", ["relay_id", "agent_name", "idempotency_key"])
def downgrade():
    with op.batch_alter_table("messages") as batch: batch.drop_constraint("uq_messages_relay_agent_idempotency", type_="unique")
    op.drop_table("pairing_invitations")
    op.drop_index("ix_agent_tokens_token_prefix", table_name="agent_tokens")
    op.drop_index("ix_agent_tokens_token_hash", table_name="agent_tokens")
    op.drop_column("agent_tokens", "token_prefix")
    op.drop_column("agent_tokens", "token_hash")
    op.drop_column("relays", "version")
