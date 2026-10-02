"""Instellingen lezen en schrijven (tabel 'instelling', sleutel/waarde).

Alle instellingen met hun standaardwaarde staan in STANDAARD. Waarden worden als
tekst opgeslagen; de hulpfuncties zetten ze om naar het juiste type.
"""

import json
import math

from ..extensions import db
from ..models import Instelling
from .tijden import is_cijfers
from .urenberekening import STANDAARD_PAUZE, Staffel

MAX_PAUZEREGELS = 5

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
    # Pauzestaffel als JSON: {"aan": ja/nee, "regels": [[grens, aftrek], ...]} (zie pauze())
    "pauze": '{"aan": true, "regels": [[5.5, 0.5]]}',
    "voettekst": "",
    "deellink_actief": "0",
    "deellink_token": "",
    "agenda_voorvoegsel": "",
    "agenda_sync_dagen_terug": "7",
    "agenda_sync_maanden_vooruit": "12",
    "agenda_pauze_tot": "",  # UTC (ISO); na een Google-limiet staat de wachtrij tot dan stil
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


def pauze_json(aan: bool, regels) -> str:
    """De waarde voor de instelling 'pauze'."""
    return json.dumps({"aan": bool(aan), "regels": [[float(g), float(a)] for g, a in regels]})


def pauze_instelling() -> dict:
    """{'aan': bool, 'regels': [(grens, aftrek), ...]}; onleesbaar -> de standaard (de oude VBA).

    De regels blijven bewaard als de pauzeaftrek uit staat (dan weer aan te zetten).
    """
    try:
        gegevens = json.loads(lees("pauze"))
        regels = [(float(g), float(a)) for g, a in gegevens["regels"]]
        aan = bool(gegevens["aan"])
    except (ValueError, TypeError, KeyError):
        return {"aan": True, "regels": list(STANDAARD_PAUZE)}
    _, fouten = controleer_pauze(aan, regels)
    if fouten:  # met de hand gewijzigd en ongeldig: nooit vreemd rekenen
        return {"aan": True, "regels": list(STANDAARD_PAUZE)}
    return {"aan": aan, "regels": regels}


def pauze() -> Staffel:
    """De pauzestaffel voor de urenberekening; () als de pauzeaftrek uit staat."""
    instelling = pauze_instelling()
    return tuple(instelling["regels"]) if instelling["aan"] else ()


def _getal_nl(waarde: float) -> str:
    return f"{waarde:g}".replace(".", ",")


def pauze_tekst(instelling: dict) -> str:
    """Leesbaar voor het logboek, bijv. 'aan: meer dan 5,5 uur: 0,5 eraf'."""
    regels = "; ".join(f"meer dan {_getal_nl(g)} uur: {_getal_nl(a)} eraf" for g, a in instelling["regels"])
    return ("aan" if instelling["aan"] else "uit") + (f": {regels}" if regels else "")


def controleer_pauze(aan: bool, regels) -> tuple[dict, list[str]]:
    """Controleer een pauzestaffel uit het formulier: ({'aan', 'regels'}, foutmeldingen).

    regels: paren (grens, aftrek) als tekst (komma of punt) of getal; een leeg paar telt niet.
    Eisen: getallen eindig en 0 of meer, grens hooguit 24, aftrek kleiner dan de grens,
    grenzen uniek en oplopend, hooguit MAX_PAUZEREGELS regels; aan = minstens één regel.
    """
    fouten: list[str] = []
    gelezen: list[tuple[float, float]] = []
    for nummer, (grens_tekst, aftrek_tekst) in enumerate(regels, start=1):
        delen = [("" if x is None else str(x)).strip().replace(",", ".") for x in (grens_tekst, aftrek_tekst)]
        if delen == ["", ""]:
            continue
        if "" in delen:
            fouten.append(f"Pauzeregel {nummer}: vul beide getallen in (grens en aftrek), of geen van beide.")
            continue
        try:
            grens, aftrek = (float(d) for d in delen)
        except ValueError:
            grens = aftrek = math.nan
        if not (math.isfinite(grens) and math.isfinite(aftrek)):
            fouten.append(f"Pauzeregel {nummer}: vul een getal in (bijvoorbeeld 5,5 en 0,5).")
        elif grens < 0 or aftrek < 0:
            fouten.append(f"Pauzeregel {nummer}: de getallen moeten 0 of meer zijn.")
        elif grens > 24:
            fouten.append(f"Pauzeregel {nummer}: de grens is hooguit 24 uur.")
        elif aftrek >= grens:
            fouten.append(f"Pauzeregel {nummer}: de pauze moet kleiner dan de grens zijn.")
        else:
            gelezen.append((grens, aftrek))
    if len(gelezen) > MAX_PAUZEREGELS:
        fouten.append(f"Je kunt hooguit {MAX_PAUZEREGELS} pauzeregels gebruiken.")
    if any(b[0] <= a[0] for a, b in zip(gelezen, gelezen[1:], strict=False)):
        fouten.append("De grenzen van de pauzeregels moeten uniek en oplopend zijn (bijvoorbeeld 5,5 en 9).")
    if aan and not gelezen and not fouten:
        fouten.append("Vul minstens één pauzeregel in, of zet de pauzeaftrek uit.")
    return {"aan": bool(aan), "regels": gelezen}, fouten


def setup_voltooid() -> bool:
    return lees_bool("setup_voltooid")
