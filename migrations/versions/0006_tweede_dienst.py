"""Dienst: tweede dienst per dag (kolom volgnummer)

Revision ID: 0006
Revises: 0005

Upgrade: bestaande diensten krijgen volgnummer 1. De unieke sleutel
(medewerker_id, datum) wordt (medewerker_id, datum, volgnummer).

Downgrade: wordt GEWEIGERD zolang er nog tweede diensten (volgnummer 2) in de
database staan; die zouden anders stilzwijgend verloren gaan. Wis eerst de
tweede diensten in het rooster (of zet een oudere back-up terug).
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# De unieke sleutel uit 0001 heeft geen naam; met deze naamgeving vindt batch hem terug
NAAMGEVING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    with op.batch_alter_table("dienst", naming_convention=NAAMGEVING) as batch_op:
        batch_op.add_column(sa.Column("volgnummer", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uq_dienst_medewerker_id", type_="unique")
        batch_op.create_unique_constraint("uq_dienst_medewerker_datum_volgnummer",
                                          ["medewerker_id", "datum", "volgnummer"])


def downgrade():
    aantal = op.get_bind().execute(sa.text("SELECT count(*) FROM dienst WHERE volgnummer != 1")).scalar()
    if aantal:
        raise RuntimeError(
            f"Terugzetten naar databaseversie 0005 kan niet: er staan nog {aantal} tweede dienst(en) "
            "in het rooster. Wis die eerst (of zet een back-up van vóór versie 1.4.0 terug).")
    with op.batch_alter_table("dienst", naming_convention=NAAMGEVING) as batch_op:
        batch_op.drop_constraint("uq_dienst_medewerker_datum_volgnummer", type_="unique")
        batch_op.drop_column("volgnummer")
        batch_op.create_unique_constraint("uq_dienst_medewerker_id", ["medewerker_id", "datum"])
