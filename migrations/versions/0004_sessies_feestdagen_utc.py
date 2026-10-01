"""Sessieversie per gebruiker, unieke feestdagen en wachttijden in UTC

- gebruiker.sessie_versie: bestaande sessies ongeldig maken na wachtwoord wijzigen,
  resetten of deactiveren.
- feestdag: een standaard feestdag (met sleutel) maar één keer per jaar. Dubbele
  regels (ontstaan door gelijktijdig aanmaken) worden eerst opgeruimd.
- sync_wachtrij.niet_voor en login_poging.tijdstip zijn voortaan in UTC. Wachtende
  agenda-taken worden direct aan de beurt gezet; oude loginpogingen vervallen.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("gebruiker") as batch_op:
        batch_op.add_column(sa.Column("sessie_versie", sa.Integer(), nullable=False,
                                      server_default="0"))

    # Dubbele standaard feestdagen opruimen: de eerste (laagste id) blijft
    op.execute(
        "DELETE FROM feestdag WHERE sleutel != '' AND id NOT IN ("
        "SELECT MIN(id) FROM feestdag WHERE sleutel != '' GROUP BY jaar, sleutel)"
    )
    op.create_index("uq_feestdag_jaar_sleutel", "feestdag", ["jaar", "sleutel"], unique=True,
                    sqlite_where=sa.text("sleutel != ''"))

    # Overgang naar UTC voor wachttijden
    op.execute("UPDATE sync_wachtrij SET niet_voor = '2000-01-01 00:00:00.000000' "
               "WHERE status = 'wacht'")
    op.execute("DELETE FROM login_poging")


def downgrade():
    op.drop_index("uq_feestdag_jaar_sleutel", table_name="feestdag")
    with op.batch_alter_table("gebruiker") as batch_op:
        batch_op.drop_column("sessie_versie")
