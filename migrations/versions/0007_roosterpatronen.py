"""Roosterpatronen: een cyclus van weken met per dag de code(s), om uit te rollen

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rooster_patroon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("naam", sa.String(length=60), nullable=False),
        sa.Column("weken", sa.Integer(), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(), nullable=False),
        sa.Column("gewijzigd_op", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("naam"),
    )
    op.create_table(
        "rooster_patroon_dag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("patroon_id", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("dag", sa.Integer(), nullable=False),
        sa.Column("codes", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["patroon_id"], ["rooster_patroon.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("patroon_id", "week", "dag", name="uq_patroon_week_dag"),
    )
    with op.batch_alter_table("rooster_patroon_dag") as batch_op:
        batch_op.create_index("ix_rooster_patroon_dag_patroon_id", ["patroon_id"])


def downgrade():
    with op.batch_alter_table("rooster_patroon_dag") as batch_op:
        batch_op.drop_index("ix_rooster_patroon_dag_patroon_id")
    op.drop_table("rooster_patroon_dag")
    op.drop_table("rooster_patroon")
