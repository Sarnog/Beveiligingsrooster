"""Back-ups van de SQLite-database.

We gebruiken de backup-API van SQLite. Die maakt een consistente kopie, ook
terwijl de app gewoon in gebruik is. Back-ups staan in <datamap>/backups.
"""

import logging
import os
import re
import secrets
import sqlite3
from datetime import timedelta

from flask import current_app

from . import instellingen, klok

log = logging.getLogger(__name__)
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


# Automatische (nachtelijke) back-ups: zonder label, bijv. rooster-20260302-020000.db
AUTOMATISCH = re.compile(r"^rooster-\d{8}-\d{6}\.db$")
TIJDELIJK = ".tmp"  # valt buiten het patroon van lijst_backups()


def _controleer_kopie(pad: str) -> None:
    """Controleer een net gemaakte kopie. Niet in orde: sqlite3.DatabaseError."""
    verbinding = sqlite3.connect(pad)
    try:
        uitkomst = verbinding.execute("PRAGMA integrity_check").fetchone()
    finally:
        verbinding.close()
    if not uitkomst or uitkomst[0] != "ok":
        raise sqlite3.DatabaseError(f"Back-up is niet in orde: {uitkomst}")


def maak_backup(label: str = "") -> str:
    """Maak een back-up en geef het pad terug. label bijv. 'voor-update'.

    De kopie wordt eerst als tijdelijk bestand (.db.tmp) geschreven en gecontroleerd
    (PRAGMA integrity_check). Pas daarna krijgt hij zijn echte naam. Mislukt er iets
    (bijv. schijf vol), dan wordt het tijdelijke bestand opgeruimd: er blijft nooit
    een lege of halve back-up staan.
    """
    stempel = klok.nu().strftime("%Y%m%d-%H%M%S")
    naam = f"{VOORVOEGSEL}{stempel}{('-' + label) if label else ''}{ACHTERVOEGSEL}"
    doel = os.path.join(backup_map(), naam)
    tijdelijk = doel + TIJDELIJK
    try:
        bron = sqlite3.connect(database_pad())
        try:
            kopie = sqlite3.connect(tijdelijk)
            try:
                with kopie:
                    bron.backup(kopie)  # veilig tijdens gebruik
            finally:
                kopie.close()
        finally:
            bron.close()
        os.chmod(tijdelijk, 0o600)
        _controleer_kopie(tijdelijk)
        os.replace(tijdelijk, doel)
    except BaseException:
        if os.path.exists(tijdelijk):
            os.remove(tijdelijk)
        raise
    log.debug("Back-up gemaakt: %s (%s bytes)", naam, os.path.getsize(doel))
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

    Alleen geldige (niet-lege) automatische back-ups tellen mee. Lege bestanden van
    een oude, mislukte back-up worden altijd opgeruimd. Back-ups met een label
    (bijv. 'voor-update') vallen hierbuiten; zie ruim_gelabelde_op().
    """
    bewaren = max(instellingen.lees_int("backup_bewaren", 30), 1)
    automatisch = [b for b in lijst_backups() if AUTOMATISCH.match(b["naam"])]
    geldig = [b for b in automatisch if b["grootte"] > 0]
    weg = [b for b in automatisch if b["grootte"] == 0] + geldig[bewaren:]
    for oud in weg:
        os.remove(os.path.join(backup_map(), oud["naam"]))
    return len(weg)


# Back-ups met een label (handmatig, voor-update, voor-import, voor-terugzetten, upload):
# ze blijven GELABELD_DAGEN staan; de nieuwste GELABELD_MINIMAAL blijven altijd.
GELABELD_DAGEN = 90
GELABELD_MINIMAAL = 10
STEMPEL = re.compile(r"^rooster-(\d{8})-\d{6}-[a-z0-9-]+\.db$")


def ruim_gelabelde_op() -> int:
    """Verwijder gelabelde back-ups ouder dan GELABELD_DAGEN (de nieuwste blijven altijd)."""
    grens = (klok.nu() - timedelta(days=GELABELD_DAGEN)).strftime("%Y%m%d")
    gelabeld = [b for b in lijst_backups() if STEMPEL.match(b["naam"])]
    verwijderd = 0
    for oud in gelabeld[GELABELD_MINIMAAL:]:
        if STEMPEL.match(oud["naam"]).group(1) < grens:
            os.remove(os.path.join(backup_map(), oud["naam"]))
            verwijderd += 1
    return verwijderd


GELDIGE_NAAM = re.compile(r"^rooster-[0-9]{8}-[0-9]{6}(-[a-z0-9-]+)?\.db$")


def pad_van(naam: str) -> str | None:
    """Veilig pad van een back-up (alleen namen die wij zelf maken)."""
    if not GELDIGE_NAAM.match(naam or ""):
        return None
    pad = os.path.join(backup_map(), naam)
    return pad if os.path.exists(pad) else None


def controleer_backupbestand(pad: str) -> str:
    """Is dit een gave database van deze app? Geeft de databaseversie (revisie) terug.

    Anders ValueError met een uitleg voor de beheerder.
    """
    try:
        verbinding = sqlite3.connect(f"file:{pad}?mode=ro", uri=True)
        try:
            tabellen = {r[0] for r in verbinding.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            uitkomst = verbinding.execute("PRAGMA integrity_check").fetchall()
            revisie = None
            if "alembic_version" in tabellen:
                rij = verbinding.execute("SELECT version_num FROM alembic_version").fetchone()
                revisie = rij[0] if rij else None
        finally:
            verbinding.close()
    except sqlite3.DatabaseError as fout:
        raise ValueError("Dit is geen geldige database-back-up.") from fout
    if not {"medewerker", "dienst", "alembic_version"} <= tabellen:
        raise ValueError("Dit bestand is geen back-up van het Beveiligingsrooster.")
    if [r[0] for r in uitkomst] != ["ok"]:
        raise ValueError("Deze back-up is beschadigd (de integriteitscontrole van SQLite faalt). "
                         "Kies een andere back-up.")
    if not revisie:
        raise ValueError("Deze back-up heeft geen databaseversie en kan niet teruggezet worden.")
    return revisie


def _migraties_map() -> str:
    return os.path.join(os.path.dirname(current_app.root_path), "migrations")


def _controleer_revisie(revisie: str) -> None:
    """Bestaat deze databaseversie in deze app? Anders is de back-up van een nieuwere versie."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", _migraties_map())
    try:
        bekend = ScriptDirectory.from_config(config).get_revision(revisie) is not None
    except Exception:  # onbekende revisie geeft een alembic-fout
        bekend = False
    if not bekend:
        raise ValueError(f"Deze back-up komt van een nieuwere versie van de app (databaseversie "
                         f"'{revisie}'). Werk de app eerst bij en zet hem daarna terug.")


def _kopieer_naar_live(pad: str) -> None:
    """Kopieer een databasebestand in de draaiende database (backup-API)."""
    from ..extensions import db

    db.session.remove()
    db.engine.dispose()
    bron = sqlite3.connect(pad)
    doel = sqlite3.connect(database_pad())
    try:
        with doel:
            bron.backup(doel)
    finally:
        bron.close()
        doel.close()
    db.engine.dispose()


def zet_terug(pad: str) -> str:
    """Zet een back-up terug. Maakt eerst zelf een back-up van de huidige stand.

    Vooraf wordt gecontroleerd of de back-up gaaf is en van deze of een oudere versie
    van de app komt; anders blijft de live database ongemoeid. De inhoud wordt met de
    backup-API in de draaiende database gekopieerd, zodat andere processen (web, worker)
    gewoon doorwerken. Daarna worden eventuele databasemigraties uitgevoerd (voor een
    back-up van een oudere versie). Mislukt dat, dan wordt de veiligheidsback-up
    automatisch teruggezet. Geeft de naam van de veiligheidsback-up terug.
    """
    import flask_migrate

    revisie = controleer_backupbestand(pad)
    log.debug("Terugzetten van %s (databaseversie %s)", os.path.basename(pad), revisie)
    _controleer_revisie(revisie)
    veiligheid = maak_backup("voor-terugzetten")
    _kopieer_naar_live(pad)
    try:
        flask_migrate.upgrade(directory=_migraties_map())
    except (SystemExit, Exception) as fout:  # Flask-Migrate stopt met sys.exit(1)
        log.exception("Databasemigratie na terugzetten mislukt; vorige stand wordt teruggezet")
        _kopieer_naar_live(veiligheid)
        raise ValueError("De back-up kon niet bijgewerkt worden naar deze versie van de app. "
                         "De vorige stand is automatisch teruggezet; er is niets veranderd.") from fout
    # Iedereen opnieuw laten inloggen: gebruikers-ID's in de back-up kunnen bij iemand
    # anders horen dan in de oude stand (zie Gebruiker.get_id)
    from ..extensions import db

    instellingen.schrijf("sessie_generatie", secrets.token_hex(8))
    db.session.commit()
    log.info("Back-up %s teruggezet; vorige stand in %s", os.path.basename(pad),
             os.path.basename(veiligheid))
    return os.path.basename(veiligheid)
