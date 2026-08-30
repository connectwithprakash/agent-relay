"""Add durable worker liveness.

Revision ID: 015
Revises: 014
"""
from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workers")}
    if "last_seen" in columns:
        return
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("last_seen", sa.DateTime(), nullable=True))
    op.execute("UPDATE workers SET last_seen = created_at WHERE last_seen IS NULL")
    with op.batch_alter_table("workers") as batch:
        batch.alter_column("last_seen", nullable=False)


def downgrade():
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("last_seen")
