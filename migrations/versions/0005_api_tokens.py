"""Persoonlijke API-tokens (voor een app)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gebruiker_id", sa.Integer(), nullable=False),
        sa.Column("naam", sa.String(length=60), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=12), nullable=False),
        sa.Column("sessie_sleutel", sa.String(length=120), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(), nullable=False),
        sa.Column("verloopt_op", sa.DateTime(), nullable=False),
        sa.Column("laatst_gebruikt", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["gebruiker_id"], ["gebruiker.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("api_token") as batch_op:
        batch_op.create_index("ix_api_token_gebruiker_id", ["gebruiker_id"])


def downgrade():
    with op.batch_alter_table("api_token") as batch_op:
        batch_op.drop_index("ix_api_token_gebruiker_id")
    op.drop_table("api_token")
