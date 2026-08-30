"""Add managed worker and harness control tables.

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa


revision = "014"
down_revision = "013"


def upgrade():
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    control_tables = {"workers", "harness_sessions", "control_leases", "control_events"}
    if control_tables.issubset(existing_tables):
        return
    if control_tables.intersection(existing_tables):
        raise RuntimeError("Existing worker control schema is incomplete")
    op.create_table(
        "workers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="online"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("relay_id", "agent_name", name="uq_workers_relay_agent"),
    )
    op.create_index("ix_workers_relay_id", "workers", ["relay_id"])
    op.create_table(
        "harness_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("relay_id", sa.String(), sa.ForeignKey("relays.id"), nullable=False),
        sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("controller_agent", sa.String(), nullable=False),
        sa.Column("profile", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="starting"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "relay_id", "controller_agent", "idempotency_key",
            name="uq_sessions_relay_controller_idempotency",
        ),
    )
    op.create_index("ix_harness_sessions_relay_id", "harness_sessions", ["relay_id"])
    op.create_index("ix_harness_sessions_worker_id", "harness_sessions", ["worker_id"])
    op.create_table(
        "control_leases",
        sa.Column("session_id", sa.String(), sa.ForeignKey("harness_sessions.id"), primary_key=True),
        sa.Column("controller_agent", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "control_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("harness_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "sequence", name="uq_control_events_session_sequence"),
    )
    op.create_index("ix_control_events_session_sequence", "control_events", ["session_id", "sequence"])


def downgrade():
    op.drop_index("ix_control_events_session_sequence", table_name="control_events")
    op.drop_table("control_events")
    op.drop_table("control_leases")
    op.drop_index("ix_harness_sessions_worker_id", table_name="harness_sessions")
    op.drop_index("ix_harness_sessions_relay_id", table_name="harness_sessions")
    op.drop_table("harness_sessions")
    op.drop_index("ix_workers_relay_id", table_name="workers")
    op.drop_table("workers")
