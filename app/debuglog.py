"""Logging van de app: console (docker compose logs) en optioneel een debuglog in ./data.

Twee omgevingsvariabelen (zie README):
- LOG_NIVEAU: DEBUG, INFO (standaard), WARNING of ERROR voor de console.
- DEBUG_LOG=1: daarnaast ALLES (ook DEBUG) naar <datamap>/logs/debug.log.

Web (alle Gunicorn-processen) en worker schrijven samen naar hetzelfde bestand met
een WatchedFileHandler. Die opent het bestand opnieuw zodra het hernoemd is. Alleen
de worker roteert (roteer()): bij MAX_BYTES wordt debug.log -> debug.log.1 enz.,
er blijven BEWAREN oude bestanden. Zo zitten de processen elkaar nooit in de weg.

Geheime tokens (ICS-feed, deellink) worden in elke logregel vervangen door '***'.
Wachtwoorden worden nergens gelogd.
"""

import logging
import os
from logging.handlers import WatchedFileHandler

NIVEAUS = ("DEBUG", "INFO", "WARNING", "ERROR")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per bestand
BEWAREN = 3  # aantal oude bestanden (debug.log.1 t/m .3)
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


def stel_in(app) -> None:
    """Stel de logging in volgens LOG_NIVEAU en DEBUG_LOG. Mag vaker aangeroepen worden."""
    wortel = logging.getLogger()
    niveau = getattr(logging, app.config["LOG_NIVEAU"])

    console = _eigen_handler("console")
    if console is None:
        console = logging.StreamHandler()
        console._rooster = "console"
        console.setFormatter(logging.Formatter(FORMAAT))
        console.addFilter(MaskeerTokens())
        wortel.addHandler(console)
    console.setLevel(niveau)

    bestandshandler = _eigen_handler("bestand")
    if app.config["DEBUG_LOG"] and bestandshandler is None:
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

    # De wortel laat door wat een van de handlers nodig heeft
    wortel.setLevel(logging.DEBUG if app.config["DEBUG_LOG"] else niveau)
    for naam in STIL:
        logging.getLogger(naam).setLevel(max(niveau, logging.WARNING))


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
