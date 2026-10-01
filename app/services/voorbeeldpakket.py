"""Voorbeeldpakket met dienstcodes en opmerking-kleurregels.

Wordt alleen geladen als de beheerder daarvoor kiest (setup-wizard of beheer).
Daarna is alles volledig aan te passen. Code 15 ontbreekt bewust: dat is de
instelbare 'blanco-code' (geen dienst).
"""

from ..extensions import db
from ..models import Dienstcode, OpmerkingKleurregel

GEEL, ROOD, ORANJE = "#FFFF00", "#FF0000", "#FFC000"
LICHTBLAUW, BLAUW, DONKERBLAUW = "#00B0F0", "#0070C0", "#002060"
LICHTGRIJS, GRIJS = "#F2F2F2", "#D9D9D9"
PASTELBLAUW, PASTELGROEN = "#DDEBF7", "#E2EFDA"
ZWART, WIT = "#000000", "#FFFFFF"

# (nummer, omschrijving, begin, eind, uren, achtergrond, tekst, cursief)
DIENSTCODES = [
    (1, "VW Hoofdloge", "11:30", "20:00", 8, GEEL, ZWART, False),
    (2, "VW Sluiten", "12:00", "20:30", 8, GEEL, ZWART, False),
    (3, "VW Avond", "14:30", "23:00", 8, GEEL, ZWART, False),
    (4, "VW Vroeg", "07:15", "15:45", 8, ROOD, WIT, False),
    (5, "VW Dag", "07:15", "16:45", 9, ROOD, WIT, False),
    (6, "VW UI", "09:30", "18:00", 8, ORANJE, ZWART, False),
    (7, "OB Vroeg", "07:30", "16:00", 8, LICHTBLAUW, ZWART, False),
    (8, "OB Dag", "08:00", "16:30", 8, BLAUW, WIT, False),
    (9, "OB Sluiten", "09:30", "18:00", 8, DONKERBLAUW, WIT, False),
    (10, "Bapo", None, None, None, LICHTGRIJS, ZWART, False),
    (11, "VW Vak", "07:15", "17:45", 10, ROOD, WIT, False),
    (12, "Ziek", "07:15", "15:45", 8, GRIJS, ZWART, False),
    (13, "Cursus", "07:15", "15:45", 8, GRIJS, ZWART, False),
    (14, "BV", "07:15", "15:45", 8, GRIJS, ZWART, False),
    (16, "EHBO", "08:30", "17:00", 8, PASTELBLAUW, ZWART, True),
    (17, "BHV", "08:30", "12:30", 4, PASTELGROEN, ZWART, True),
    (18, "Ziek (9 uur)", "07:15", "16:45", 9, GRIJS, ZWART, False),
    (19, "Verlof", "07:15", "15:45", 8, PASTELGROEN, ZWART, True),
]

# (tekst, achtergrond, tweede kleur voor verloop, tekstkleur)
KLEURREGELS = [
    ("Locatie A", "#FF0000", "#FFFF00", ZWART),
    ("Locatie B", "#FFFF00", "#A9D08E", ZWART),
]


def laad_voorbeeldpakket() -> tuple[int, int]:
    """Voeg ontbrekende codes en kleurregels toe. Bestaande nummers blijven staan.

    Geeft (aantal nieuwe codes, aantal nieuwe kleurregels) terug.
    """
    nieuwe_codes = 0
    for nummer, oms, begin, eind, uren, achtergrond, tekst, cursief in DIENSTCODES:
        if Dienstcode.query.filter_by(nummer=nummer).first() is not None:
            continue
        db.session.add(
            Dienstcode(
                nummer=nummer,
                omschrijving=oms,
                std_begin=begin,
                std_eind=eind,
                std_uren=uren,
                kleur_achtergrond=achtergrond,
                kleur_tekst=tekst,
                vet=True,  # alle dienstnamen staan vet in het rooster
                cursief=cursief,
                in_agenda=True,
                # Bapo heeft geen tijden: als hele-dag-afspraak in de agenda
                hele_dag_zonder_tijden=begin is None,
            )
        )
        nieuwe_codes += 1

    nieuwe_regels = 0
    for tekst_regel, achtergrond, achtergrond2, tekstkleur in KLEURREGELS:
        if OpmerkingKleurregel.query.filter_by(tekst=tekst_regel).first() is not None:
            continue
        db.session.add(
            OpmerkingKleurregel(
                tekst=tekst_regel,
                kleur_achtergrond=achtergrond,
                kleur_achtergrond2=achtergrond2,
                kleur_tekst=tekstkleur,
            )
        )
        nieuwe_regels += 1
    db.session.commit()
    return nieuwe_codes, nieuwe_regels
