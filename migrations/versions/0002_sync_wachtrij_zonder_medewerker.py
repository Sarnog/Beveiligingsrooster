"""Sync-wachtrij: taak mag blijven bestaan als de medewerker is verwijderd

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _nieuwe_tabel(naam: str, nullable: bool, ondelete: str):
    """Definitie van de sync_wachtrij-tabel (SQLite kan een koppeling niet los wijzigen)."""
    return op.create_table(
        naam,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("medewerker_id", sa.Integer(), nullable=nullable),
        sa.Column("datum", sa.Date(), nullable=True),
        sa.Column("soort", sa.String(length=20), nullable=False),
        sa.Column("niet_voor", sa.DateTime(), nullable=False),
        sa.Column("pogingen", sa.Integer(), nullable=False),
        sa.Column("laatste_fout", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("aangemaakt_op", sa.DateTime(), nullable=False),
        sa.Column("extra", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["medewerker_id"], ["medewerker.id"], ondelete=ondelete),
        sa.PrimaryKeyConstraint("id"),
    )


def _vervang(nullable: bool, ondelete: str) -> None:
    kolommen = ("id, medewerker_id, datum, soort, niet_voor, pogingen, laatste_fout, status, "
                "aangemaakt_op, extra")
    _nieuwe_tabel("sync_wachtrij_nieuw", nullable, ondelete)
    op.execute(f"INSERT INTO sync_wachtrij_nieuw ({kolommen}) SELECT {kolommen} FROM sync_wachtrij")
    op.drop_index("ix_sync_wachtrij_niet_voor", table_name="sync_wachtrij")
    op.drop_index("ix_sync_wachtrij_status", table_name="sync_wachtrij")
    op.drop_table("sync_wachtrij")
    op.rename_table("sync_wachtrij_nieuw", "sync_wachtrij")
    op.create_index("ix_sync_wachtrij_niet_voor", "sync_wachtrij", ["niet_voor"])
    op.create_index("ix_sync_wachtrij_status", "sync_wachtrij", ["status"])


def upgrade():
    _vervang(nullable=True, ondelete="SET NULL")


def downgrade():
    op.execute("DELETE FROM sync_wachtrij WHERE medewerker_id IS NULL")
    _vervang(nullable=False, ondelete="CASCADE")
