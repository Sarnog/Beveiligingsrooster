"""Eenmalige setup-code.

Zolang de setup niet is afgerond, vraagt /setup eerst om deze code. Zo kan een
willekeurige bezoeker de installatie niet 'kapen'. De code staat in een bestand
in de datamap en wordt ook in het log getoond. Na afronding wordt het bestand
verwijderd en is de code ongeldig.
"""

import hmac
import logging
import os
import secrets

from flask import current_app

_ALFABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # geen 0/O en 1/I (verwarrend)
log = logging.getLogger(__name__)


def _pad() -> str:
    return os.path.join(current_app.config["DATA_MAP"], "setup-code.txt")


def lees_code() -> str | None:
    """De huidige code, of None als er (nog) geen is."""
    try:
        with open(_pad(), encoding="utf-8") as bestand:
            code = bestand.read().strip()
            return code or None
    except FileNotFoundError:
        return None
    except PermissionError as fout:
        from .. import rechten_melding

        raise RuntimeError(rechten_melding(_pad())) from fout


def haal_of_maak_code() -> str:
    """Geef de bestaande code, of maak een nieuwe aan (en toon die in het log)."""
    code = lees_code()
    if code:
        return code
    code = "-".join("".join(secrets.choice(_ALFABET) for _ in range(4)) for _ in range(3))
    pad = _pad()
    # Bestand alleen leesbaar voor de eigenaar (chmod 600)
    try:
        descriptor = os.open(pad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as bestand:
            bestand.write(code + "\n")
    except PermissionError as fout:
        from .. import rechten_melding

        raise RuntimeError(rechten_melding(pad)) from fout
    log.warning("SETUP-CODE voor de eerste installatie: %s", code)
    return code


def controleer_code(invoer: str) -> bool:
    """True als de ingevoerde code klopt (hoofdletterongevoelig, spaties genegeerd)."""
    code = lees_code()
    if not code or not invoer:
        return False
    schoon = invoer.strip().upper().replace(" ", "")
    return hmac.compare_digest(schoon.encode(), code.encode())


def verwijder_code() -> None:
    try:
        os.remove(_pad())
    except FileNotFoundError:
        pass
