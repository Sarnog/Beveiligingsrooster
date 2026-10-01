"""Logging van de app: console (docker compose logs) en optioneel een debuglog in ./data.

Twee omgevingsvariabelen (zie README):
- LOG_NIVEAU: DEBUG, INFO (standaard), WARNING of ERROR voor de console.
- DEBUG_LOG=1: daarnaast ALLES (ook DEBUG) naar <datamap>/logs/debug.log.

Beide zijn ook in te stellen via Beheer > Debuglog (instellingen 'log_niveau' en
'debug_log'); die gaan dan voor de omgevingsvariabelen. Elk proces (Gunicorn-workers
en de worker) kijkt hooguit elke VERVERS_SECONDEN of de instelling veranderd is
(ververs()), dus een wijziging is binnen een halve minuut overal actief.

Web (alle Gunicorn-processen) en worker schrijven samen naar hetzelfde bestand met
een WatchedFileHandler. Die opent het bestand opnieuw zodra het hernoemd is. Alleen
de worker roteert (roteer()): bij MAX_BYTES wordt debug.log -> debug.log.1 enz.,
er blijven BEWAREN oude bestanden. Zo zitten de processen elkaar nooit in de weg.

Geheime tokens (ICS-feed, deellink) worden in elke logregel vervangen door '***'.
Wachtwoorden worden nergens gelogd.
"""

import logging
import os
import time
from logging.handlers import WatchedFileHandler

NIVEAUS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per bestand
BEWAREN = 3  # aantal oude bestanden (debug.log.1 t/m .3)
VERVERS_SECONDEN = 15  # zo vaak kijkt elk proces of de loginstelling in Beheer veranderd is
FORMAAT = "%(asctime)s %(levelname)s [%(process)d %(name)s] %(message)s"

# Bibliotheken loggen pas vanaf WARNING, ook als de app op DEBUG staat. Belangrijk:
# SQLAlchemy op INFO zou alle SQL mét parameters loggen (tokens, wachtwoord-hashes).
STIL = ("urllib3", "googleapiclient", "google", "sqlalchemy", "werkzeug", "PIL", "openpyxl")


def bestand(data_map: str) -> str:
    return os.path.join(data_map, "logs", "debug.log")


class MaskeerTokens(logging.Filter):
    """Vervangt geheime tokens in de logregel (zie app/toegangslog.py)."""

    def filter(self, record: logging.LogRecord) -> bool:
        from .toegangslog import maskeer_tokens

        try:
            bericht = record.getMessage()
        except Exception:  # verkeerde %-argumenten: laat logging zelf de fout melden
            return True
        gemaskeerd = maskeer_tokens(bericht)
        if gemaskeerd != bericht:
            record.msg, record.args = gemaskeerd, None
        return True


def _eigen_handler(soort: str) -> logging.Handler | None:
    return next((h for h in logging.getLogger().handlers if getattr(h, "_rooster", "") == soort), None)


def effectief(app) -> tuple[str, bool]:
    """(logniveau, debuglog aan): de instelling uit Beheer, anders de omgevingsvariabelen.

    Werkt alleen binnen een app-context; zonder (bruikbare) database: de omgeving.
    """
    niveau, aan = app.config["LOG_NIVEAU"], app.config["DEBUG_LOG"]
    try:
        from .services import instellingen

        eigen_niveau = instellingen.lees("log_niveau").strip().upper()
        eigen_aan = instellingen.lees("debug_log").strip()
    except Exception:  # bijv. de database is nog niet aangemaakt
        from .extensions import db

        db.session.rollback()
        return niveau, aan
    if eigen_niveau in NIVEAUS:
        niveau = eigen_niveau
    if eigen_aan in ("0", "1"):
        aan = eigen_aan == "1"
    return niveau, aan


def stel_in(app, niveau: str | None = None, aan: bool | None = None) -> None:
    """Stel de logging in (standaard volgens LOG_NIVEAU en DEBUG_LOG). Mag vaker aangeroepen."""
    niveau_tekst = niveau or app.config["LOG_NIVEAU"]
    aan = app.config["DEBUG_LOG"] if aan is None else aan
    wortel = logging.getLogger()
    niveau = getattr(logging, niveau_tekst)

    console = _eigen_handler("console")
    if console is None:
        console = logging.StreamHandler()
        console._rooster = "console"
        console.setFormatter(logging.Formatter(FORMAAT))
        console.addFilter(MaskeerTokens())
        wortel.addHandler(console)
    console.setLevel(niveau)

    bestandshandler = _eigen_handler("bestand")
    if aan and bestandshandler is None:
        pad = bestand(app.config["DATA_MAP"])
        os.makedirs(os.path.dirname(pad), mode=0o750, exist_ok=True)
        try:
            bestandshandler = WatchedFileHandler(pad, encoding="utf-8")
        except PermissionError as fout:
            from . import rechten_melding

            raise RuntimeError(rechten_melding(pad)) from fout
        bestandshandler._rooster = "bestand"
        bestandshandler.setLevel(logging.DEBUG)
        bestandshandler.setFormatter(logging.Formatter(FORMAAT))
        bestandshandler.addFilter(MaskeerTokens())
        wortel.addHandler(bestandshandler)
        os.chmod(pad, 0o640)
    elif not aan and bestandshandler is not None:
        wortel.removeHandler(bestandshandler)
        bestandshandler.close()

    # De wortel laat door wat een van de handlers nodig heeft
    wortel.setLevel(logging.DEBUG if aan else niveau)
    for naam in STIL:
        logging.getLogger(naam).setLevel(max(niveau, logging.WARNING))
    app.extensions["logstand"] = {"niveau": niveau_tekst, "aan": aan, "gecontroleerd": time.monotonic()}


def stand(app) -> dict:
    """De logging zoals die nu in dit proces staat ({'niveau': ..., 'aan': ...})."""
    standaard = {"niveau": app.config["LOG_NIVEAU"], "aan": app.config["DEBUG_LOG"]}
    return app.extensions.get("logstand") or standaard


def ververs(app, direct: bool = False) -> None:
    """Pas een gewijzigde loginstelling uit Beheer toe (hooguit elke VERVERS_SECONDEN)."""
    huidig = app.extensions.get("logstand") or {}
    if not direct and time.monotonic() - huidig.get("gecontroleerd", 0) < VERVERS_SECONDEN:
        return
    niveau, aan = effectief(app)
    if (niveau, aan) != (huidig.get("niveau"), huidig.get("aan")):
        logging.getLogger(__name__).info("Logniveau %s, debuglog %s", niveau, "aan" if aan else "uit")
        stel_in(app, niveau, aan)
    else:
        huidig["gecontroleerd"] = time.monotonic()


def verwijder_handlers() -> None:
    """Haal de eigen handlers weg (voor tests)."""
    wortel = logging.getLogger()
    for handler in list(wortel.handlers):
        if getattr(handler, "_rooster", ""):
            wortel.removeHandler(handler)
            handler.close()


def roteer(data_map: str) -> bool:
    """Roteer debug.log als hij groter is dan MAX_BYTES (alleen de worker doet dit)."""
    pad = bestand(data_map)
    try:
        if os.path.getsize(pad) <= MAX_BYTES:
            return False
    except FileNotFoundError:
        return False
    for nummer in range(BEWAREN - 1, 0, -1):
        if os.path.exists(f"{pad}.{nummer}"):
            os.replace(f"{pad}.{nummer}", f"{pad}.{nummer + 1}")
    os.replace(pad, f"{pad}.1")
    return True


def laatste_regels(data_map: str, aantal: int = 500) -> list[str]:
    """De laatste regels van debug.log (leest hooguit de laatste 512 kB)."""
    pad = bestand(data_map)
    if not os.path.exists(pad):
        return []
    with open(pad, "rb") as invoer:
        invoer.seek(0, os.SEEK_END)
        invoer.seek(max(invoer.tell() - 512 * 1024, 0))
        tekst = invoer.read().decode("utf-8", errors="replace")
    return tekst.splitlines()[-aantal:]
