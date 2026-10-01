"""Instellingen lezen en schrijven (tabel 'instelling', sleutel/waarde).

Alle instellingen met hun standaardwaarde staan in STANDAARD. Waarden worden als
tekst opgeslagen; de hulpfuncties zetten ze om naar het juiste type.
"""

import math

from ..extensions import db
from ..models import Instelling
from .tijden import is_cijfers

# Sleutel -> standaardwaarde (altijd als tekst)
STANDAARD: dict[str, str] = {
    "setup_voltooid": "0",
    "teamnaam": "Beveiligingsrooster",
    "tijdzone": "",  # leeg = TZ uit de omgeving (standaard Europe/Amsterdam), zie klok.py
    "eerste_jaar": "",
    "toeslag_zaterdag": "1.5",
    "toeslag_zondag": "2.0",
    "toeslag_feestdag": "",  # leeg = geen feestdagtoeslag (zoals in Excel)
    "logboek_dagen": "31",
    "logboek_uren": "0",
    "blanco_code": "15",
    "opmerkingtijden_meetellen": "0",
    "voettekst": "",
    "deellink_actief": "0",
    "deellink_token": "",
    "agenda_voorvoegsel": "",
    "agenda_sync_dagen_terug": "7",
    "agenda_sync_maanden_vooruit": "12",
    "backup_bewaren": "30",
    "log_niveau": "",  # leeg = LOG_NIVEAU uit .env; anders DEBUG, INFO, WARNING of ERROR
    "debug_log": "",  # leeg = DEBUG_LOG uit .env; "1" = aan, "0" = uit
    "laatst_bijgewerkt": "",
    "sessie_generatie": "",  # verandert na het terugzetten van een back-up: iedereen uitloggen
}


def lees(sleutel: str) -> str:
    """Lees een instelling als tekst (of de standaardwaarde)."""
    rij = db.session.get(Instelling, sleutel)
    if rij is None:
        return STANDAARD.get(sleutel, "")
    return rij.waarde


def schrijf(sleutel: str, waarde) -> None:
    """Sla een instelling op (commit doet de aanroeper)."""
    tekst = "" if waarde is None else str(waarde)
    rij = db.session.get(Instelling, sleutel)
    if rij is None:
        db.session.add(Instelling(sleutel=sleutel, waarde=tekst))
    else:
        rij.waarde = tekst


def lees_bool(sleutel: str) -> bool:
    return lees(sleutel).strip() in ("1", "true", "ja", "aan")


def lees_int(sleutel: str, standaard: int = 0) -> int:
    try:
        return int(lees(sleutel))
    except ValueError:
        return standaard


def lees_float(sleutel: str) -> float | None:
    """Lees een getal (komma of punt). Leeg, ongeldig, inf of nan -> None."""
    tekst = lees(sleutel).strip().replace(",", ".")
    if tekst == "":
        return None
    try:
        waarde = float(tekst)
    except ValueError:
        return None
    return waarde if math.isfinite(waarde) else None


def blanco_code() -> int | None:
    """Het codenummer dat 'geen dienst' betekent (standaard 15), of None."""
    tekst = lees("blanco_code").strip()
    return int(tekst) if is_cijfers(tekst) else None


def toeslagen() -> dict:
    """Alle toeslagfactoren in één keer (voor de urenberekening)."""
    return {
        "factor_zaterdag": lees_float("toeslag_zaterdag") or 1.5,
        "factor_zondag": lees_float("toeslag_zondag") or 2.0,
        "factor_feestdag": lees_float("toeslag_feestdag"),
    }


def setup_voltooid() -> bool:
    return lees_bool("setup_voltooid")
