"""Back-ups van de SQLite-database.

We gebruiken de backup-API van SQLite. Die maakt een consistente kopie, ook
terwijl de app gewoon in gebruik is. Back-ups staan in <datamap>/backups.
"""

import os
import sqlite3

from flask import current_app

from . import instellingen, klok

VOORVOEGSEL = "rooster-"
ACHTERVOEGSEL = ".db"


def backup_map() -> str:
    pad = os.path.join(current_app.config["DATA_MAP"], "backups")
    os.makedirs(pad, exist_ok=True)
    return pad


def database_pad() -> str:
    """Pad van het databasebestand (uit de SQLAlchemy-URL 'sqlite:///...')."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise RuntimeError("Back-ups werken alleen met SQLite.")
    return uri.removeprefix("sqlite:///")


def maak_backup(label: str = "") -> str:
    """Maak een back-up en geef het pad terug. label bijv. 'voor-update'."""
    stempel = klok.nu().strftime("%Y%m%d-%H%M%S")
    naam = f"{VOORVOEGSEL}{stempel}{('-' + label) if label else ''}{ACHTERVOEGSEL}"
    doel = os.path.join(backup_map(), naam)
    bron = sqlite3.connect(database_pad())
    kopie = sqlite3.connect(doel)
    try:
        with kopie:
            bron.backup(kopie)  # veilig tijdens gebruik
    finally:
        kopie.close()
        bron.close()
    os.chmod(doel, 0o600)
    return doel


def lijst_backups() -> list[dict]:
    """Alle back-ups, nieuwste eerst, met naam, grootte en tijdstip."""
    map_ = backup_map()
    resultaat = []
    for naam in os.listdir(map_):
        if naam.startswith(VOORVOEGSEL) and naam.endswith(ACHTERVOEGSEL):
            pad = os.path.join(map_, naam)
            resultaat.append({"naam": naam, "grootte": os.path.getsize(pad),
                              "tijd": os.path.getmtime(pad)})
    return sorted(resultaat, key=lambda b: b["naam"], reverse=True)


def ruim_oude_op() -> int:
    """Bewaar alleen de nieuwste N automatische back-ups (instelling 'backup_bewaren').

    Back-ups met een label (bijv. 'voor-update') tellen niet mee en blijven staan.
    """
    bewaren = max(instellingen.lees_int("backup_bewaren", 30), 1)
    automatisch = [b for b in lijst_backups() if b["naam"].count("-") == 2]
    verwijderd = 0
    for oud in automatisch[bewaren:]:
        os.remove(os.path.join(backup_map(), oud["naam"]))
        verwijderd += 1
    return verwijderd
