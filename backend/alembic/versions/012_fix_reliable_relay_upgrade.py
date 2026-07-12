"""Fix reliable relay upgrade compatibility.

Revision ID: 012
Revises: 011
"""
import hashlib

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"


def _unique_names(bind) -> set[str | None]:
    return {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints("agent_tokens")
    }


def _deduplicate_credentials(bind, columns: set[str]) -> None:
    """Keep the newest creator credential, or otherwise the newest credential."""
    ordering = ["relay_id", "agent_name"]
    if "is_creator" in columns:
        ordering.append("CASE WHEN is_creator THEN 1 ELSE 0 END DESC")
    if "created_at" in columns:
        ordering.append("created_at DESC")
    ordering.append("id DESC")
    rows = bind.execute(
        sa.text(
            "SELECT id, relay_id, agent_name FROM agent_tokens ORDER BY "
            + ", ".join(ordering)
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        identity = (row["relay_id"], row["agent_name"])
        if identity in seen:
            duplicate_ids.append(row["id"])
        else:
            seen.add(identity)
    if duplicate_ids:
        tokens = sa.table("agent_tokens", sa.column("id"))
        bind.execute(sa.delete(tokens).where(tokens.c.id.in_(duplicate_ids)))


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    join_code = next(
        column
        for column in sa.inspect(bind).get_columns("relays")
        if column["name"] == "join_code"
    )
    if getattr(join_code["type"], "length", None) != 64:
        if dialect == "sqlite":
            with op.batch_alter_table("relays") as batch:
                batch.alter_column(
                    "join_code", existing_type=join_code["type"], type_=sa.String(64)
                )
        else:
            op.alter_column(
                "relays", "join_code", existing_type=join_code["type"], type_=sa.String(64)
            )

    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("agent_tokens")
    }
    if "uq_agent_tokens_relay_agent" not in _unique_names(bind):
        _deduplicate_credentials(bind, columns)

    if "token" in columns:
        rows = bind.execute(
            sa.text(
                "SELECT id, token FROM agent_tokens "
                "WHERE token_hash IS NULL OR token_prefix IS NULL"
            )
        ).mappings()
        for row in rows:
            raw = row["token"]
            if not raw:
                raise RuntimeError(
                    f"agent_tokens row {row['id']} has no usable credential to migrate"
                )
            bind.execute(
                sa.text(
                    "UPDATE agent_tokens "
                    "SET token_hash=:hash, token_prefix=:prefix WHERE id=:id"
                ),
                {
                    "hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "prefix": raw[:12],
                    "id": row["id"],
                },
            )

        # Plaintext bearer credentials must not survive the hash migration.
        with op.batch_alter_table("agent_tokens") as batch:
            batch.drop_column("token")

    incomplete = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM agent_tokens "
            "WHERE token_hash IS NULL OR token_prefix IS NULL"
        )
    ).scalar_one()
    if incomplete:
        raise RuntimeError(
            f"{incomplete} agent token rows are missing hashed credential data"
        )

    token_columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns("agent_tokens")
    }
    with op.batch_alter_table("agent_tokens") as batch:
        if token_columns["token_hash"].get("nullable", True):
            batch.alter_column(
                "token_hash", existing_type=sa.String(64), nullable=False
            )
        if token_columns["token_prefix"].get("nullable", True):
            batch.alter_column(
                "token_prefix", existing_type=sa.String(16), nullable=False
            )
        if "uq_agent_tokens_relay_agent" not in _unique_names(bind):
            batch.create_unique_constraint(
                "uq_agent_tokens_relay_agent", ["relay_id", "agent_name"]
            )


def downgrade():
    bind = op.get_bind()
    if "uq_agent_tokens_relay_agent" in _unique_names(bind):
        with op.batch_alter_table("agent_tokens") as batch:
            batch.drop_constraint("uq_agent_tokens_relay_agent", type_="unique")
    # Credential hashing and the join-code widening are intentionally retained:
    # restoring plaintext secrets or narrowing live 48-character values is unsafe.