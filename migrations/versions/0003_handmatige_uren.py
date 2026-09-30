"""Dienst: zelf ingevulde uren (zoals in Excel bij diensten zonder tijden)

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dienst") as batch_op:
        batch_op.add_column(sa.Column("uren_handmatig", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("dienst") as batch_op:
        batch_op.drop_column("uren_handmatig")
