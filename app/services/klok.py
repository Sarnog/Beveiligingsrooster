"""De klok van de app: altijd in de tijdzone uit de instellingen (standaard TZ uit de omgeving).

We gebruiken zoneinfo met het pakket 'tzdata', zodat de juiste tijd (inclusief
zomer- en wintertijd) ook klopt als het besturingssysteem zelf geen
tijdzonebestanden heeft, zoals in een kale container.

Tijdstempels in de database zijn 'naïef' (zonder tijdzone-info):
- lokale tijd (nu()) voor alles wat de gebruiker ziet: logboek, diensten, back-upnamen;
- UTC (utc_nu()) voor interne wachttijden: de loginblokkade en de agenda-wachtrij.
  UTC kent geen dubbel uur bij de overgang naar wintertijd, dus wachttijden kloppen altijd.
"""

import os
import time
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

STANDAARD_TIJDZONE = "Europe/Amsterdam"


def standaard_tijdzone() -> str:
    """De tijdzone uit de omgeving (TZ), of Europe/Amsterdam."""
    return os.environ.get("TZ") or STANDAARD_TIJDZONE


def is_geldige_tijdzone(naam: str) -> bool:
    """True als `naam` een bestaande IANA-tijdzone is (bijv. 'Europe/Amsterdam')."""
    if not naam or not isinstance(naam, str):
        return False
    try:
        ZoneInfo(naam)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


# Per database: (tijdstip van lezen, tijdzone). Zo lezen we de instelling hooguit
# één keer per CACHE_SECONDEN, via een eigen verbinding (los van de sessie).
CACHE_SECONDEN = 60
_cache: dict[str, tuple[float, str]] = {}


def _lees_instelling() -> str:
    """De ruwe instelling 'tijdzone' uit de database ('' als die er niet is)."""
    from flask import has_app_context

    if not has_app_context():
        return ""
    from sqlalchemy import text

    from ..extensions import db

    sleutel = str(db.engine.url)
    bewaard = _cache.get(sleutel)
    if bewaard and time.monotonic() - bewaard[0] < CACHE_SECONDEN:
        return bewaard[1]
    try:
        with db.engine.connect() as verbinding:
            waarde = verbinding.execute(
                text("SELECT waarde FROM instelling WHERE sleutel = 'tijdzone'")).scalar() or ""
    except Exception:  # database nog niet aangemaakt (eerste start)
        waarde = ""
    _cache[sleutel] = (time.monotonic(), waarde.strip())
    return waarde.strip()


def wis_cache() -> None:
    """Na het wijzigen van de tijdzone: direct de nieuwe waarde gebruiken."""
    _cache.clear()


def tijdzone_naam() -> str:
    """De tijdzone van de app: de instelling 'tijdzone', anders TZ uit de omgeving.

    Eén bron van waarheid voor de klok, de ICS-feed en Google Agenda.
    """
    naam = _lees_instelling()
    if is_geldige_tijdzone(naam):
        return naam
    standaard = standaard_tijdzone()
    return standaard if is_geldige_tijdzone(standaard) else STANDAARD_TIJDZONE


def tijdzone() -> ZoneInfo:
    return ZoneInfo(tijdzone_naam())


def nu() -> datetime:
    """Huidige lokale tijd, zonder tijdzone-info en zonder microseconden."""
    return datetime.now(tijdzone()).replace(tzinfo=None, microsecond=0)


def utc_nu() -> datetime:
    """Huidige tijd in UTC, zonder tijdzone-info (voor wachttijden en blokkades)."""
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def vandaag() -> date:
    return nu().date()
