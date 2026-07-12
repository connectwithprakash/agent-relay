"""Reliable relay core schema.

Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _constraint_names(bind, table_name: str) -> set[str | None]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints(table_name)
    }


def upgrade():
    bind = op.get_bind()
    relay_columns = _column_names(bind, "relays")
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

    if "idempotency_key" not in _column_names(bind, "messages"):
        op.add_column("messages", sa.Column("idempotency_key", sa.String(255), nullable=True))

    tables = set(sa.inspect(bind).get_table_names())
    if "agent_tokens" not in tables:
        op.create_table(
            "agent_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("token_prefix", sa.String(16), nullable=False),
            sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False),
            sa.Column("agent_name", sa.String(), nullable=False),
            sa.Column("is_creator", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    else:
        token_columns = _column_names(bind, "agent_tokens")
        if "token_hash" not in token_columns:
            op.add_column("agent_tokens", sa.Column("token_hash", sa.String(64), nullable=True))
        if "token_prefix" not in token_columns:
            op.add_column("agent_tokens", sa.Column("token_prefix", sa.String(16), nullable=True))

    token_indexes = _index_names(bind, "agent_tokens")
    if "ix_agent_tokens_token_hash" not in token_indexes:
        op.create_index("ix_agent_tokens_token_hash", "agent_tokens", ["token_hash"], unique=True)
    if "ix_agent_tokens_token_prefix" not in token_indexes:
        op.create_index("ix_agent_tokens_token_prefix", "agent_tokens", ["token_prefix"])

    tables = set(sa.inspect(bind).get_table_names())
    if "pairing_invitations" not in tables:
        op.create_table(
            "pairing_invitations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False),
            sa.Column("agent_name", sa.String(), nullable=False),
            sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("redeemed_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "relay_id", "agent_name", name="uq_pairing_invitation_relay_agent"
            ),
        )
    if "ix_pairing_invitations_relay_id" not in _index_names(bind, "pairing_invitations"):
        op.create_index(
            "ix_pairing_invitations_relay_id", "pairing_invitations", ["relay_id"]
        )

    if "uq_messages_relay_agent_idempotency" not in _constraint_names(bind, "messages"):
        with op.batch_alter_table("messages") as batch:
            batch.create_unique_constraint(
                "uq_messages_relay_agent_idempotency",
                ["relay_id", "agent_name", "idempotency_key"],
            )


def downgrade():
    bind = op.get_bind()
    if "uq_messages_relay_agent_idempotency" in _constraint_names(bind, "messages"):
        with op.batch_alter_table("messages") as batch:
            batch.drop_constraint("uq_messages_relay_agent_idempotency", type_="unique")
    if "pairing_invitations" in sa.inspect(bind).get_table_names():
        op.drop_table("pairing_invitations")
    token_columns = _column_names(bind, "agent_tokens")
    token_indexes = _index_names(bind, "agent_tokens")
    if "ix_agent_tokens_token_prefix" in token_indexes:
        op.drop_index("ix_agent_tokens_token_prefix", table_name="agent_tokens")
    if "ix_agent_tokens_token_hash" in token_indexes:
        op.drop_index("ix_agent_tokens_token_hash", table_name="agent_tokens")
    # A canonical revision-010 database has no agent_tokens table; revision 011
    # created it. Historical create_all databases can have the legacy `token`
    # table already, in which case preserve that table and remove only 011 fields.
    if "token" not in token_columns:
        op.drop_table("agent_tokens")
    else:
        with op.batch_alter_table("agent_tokens") as batch:
            if "token_prefix" in token_columns:
                batch.drop_column("token_prefix")
            if "token_hash" in token_columns:
                batch.drop_column("token_hash")
    if "idempotency_key" in _column_names(bind, "messages"):
        with op.batch_alter_table("messages") as batch:
            batch.drop_column("idempotency_key")
    relay_columns = _column_names(bind, "relays")
    with op.batch_alter_table("relays") as batch:
        for column_name in (
            "max_skip_count",
            "turns_waited",
            "min_agents",
            "max_agents",
            "agent_instructions",
            "description",
            "version",
        ):
            if column_name in relay_columns:
                batch.drop_column(column_name)