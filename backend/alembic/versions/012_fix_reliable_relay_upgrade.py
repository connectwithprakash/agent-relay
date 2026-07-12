"""Fix reliable relay upgrade compatibility.

Revision ID: 012
Revises: 011
"""
import hashlib

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # PostgreSQL enforces the original VARCHAR(6); SQLite did not reveal this.
    if dialect == "sqlite":
        with op.batch_alter_table("relays") as batch:
            batch.alter_column("join_code", existing_type=sa.String(6), type_=sa.String(64))
    else:
        op.alter_column("relays", "join_code", existing_type=sa.String(6), type_=sa.String(64))

    columns = {column["name"] for column in sa.inspect(bind).get_columns("agent_tokens")}
    if "token" in columns:
        rows = bind.execute(sa.text("SELECT id, token FROM agent_tokens WHERE token_hash IS NULL")).mappings()
        for row in rows:
            raw = row["token"]
            if raw:
                op.execute(
                    sa.text("UPDATE agent_tokens SET token_hash=:hash, token_prefix=:prefix WHERE id=:id").bindparams(
                        hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(), prefix=raw[:12], id=row["id"]
                    )
                )
        if dialect == "sqlite":
            with op.batch_alter_table("agent_tokens") as batch:
                batch.alter_column("token", existing_type=sa.String(), nullable=True)
        else:
            op.alter_column("agent_tokens", "token", existing_type=sa.String(), nullable=True)

    inspector = sa.inspect(bind)
    uniques = {u.get("name") for u in inspector.get_unique_constraints("agent_tokens")}
    if "uq_agent_tokens_relay_agent" not in uniques:
        # Legacy installations could contain multiple credentials for one
        # participant. Preserve the earliest credential deterministically and
        # revoke later duplicates before enforcing the one-token contract.
        duplicate_ids = bind.execute(
            sa.text(
                "SELECT id FROM agent_tokens "
                "WHERE id NOT IN ("
                "SELECT MIN(id) FROM agent_tokens GROUP BY relay_id, agent_name"
                ")"
            )
        ).scalars()
        duplicate_ids = list(duplicate_ids)
        if duplicate_ids:
            bind.execute(
                sa.delete(sa.table("agent_tokens", sa.column("id"))).where(
                    sa.column("id").in_(duplicate_ids)
                )
            )
        with op.batch_alter_table("agent_tokens") as batch:
            batch.create_unique_constraint("uq_agent_tokens_relay_agent", ["relay_id", "agent_name"])


def downgrade():
    with op.batch_alter_table("agent_tokens") as batch:
        batch.drop_constraint("uq_agent_tokens_relay_agent", type_="unique")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("relays") as batch:
            batch.alter_column("join_code", existing_type=sa.String(64), type_=sa.String(6))
    else:
        op.alter_column("relays", "join_code", existing_type=sa.String(64), type_=sa.String(6))
