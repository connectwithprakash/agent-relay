"""Add creator scope to one-time pairing invitations.

Revision ID: 016
Revises: 015
"""
from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"


def upgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("pairing_invitations")
    }
    if "is_creator" not in columns:
        with op.batch_alter_table("pairing_invitations") as batch:
            batch.add_column(
                sa.Column("is_creator", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("pairing_invitations")
    }
    if "is_creator" in columns:
        with op.batch_alter_table("pairing_invitations") as batch:
            batch.drop_column("is_creator")
