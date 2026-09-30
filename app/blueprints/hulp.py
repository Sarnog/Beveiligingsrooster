"""Kleine hulpfuncties die door meerdere blueprints gebruikt worden."""

import re
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

KLEUR_PATROON = re.compile(r"^#[0-9A-Fa-f]{6}$")


def beheerder_vereist(functie):
    """Decorator: alleen een ingelogde beheerder mag deze route gebruiken (anders 403)."""

    @wraps(functie)
    @login_required
    def binnen(*args, **kwargs):
        if not current_user.is_beheerder:
            abort(403)
        return functie(*args, **kwargs)

    return binnen


def kleur(waarde: str | None, standaard: str) -> str:
    """Geef een geldige #RRGGBB-kleur terug (in hoofdletters) of de standaard."""
    if waarde and KLEUR_PATROON.match(waarde.strip()):
        return waarde.strip().upper()
    return standaard


def vinkje(formulier, naam: str) -> bool:
    """True als een checkbox aangevinkt is."""
    return formulier.get(naam) in ("1", "on", "ja", "true")


def getal(tekst: str | None) -> float | None:
    """'1.659,5' / '1659,5' / '1659.5' -> 1659.5; leeg of ongeldig -> None."""
    if tekst is None:
        return None
    schoon = tekst.strip().replace(" ", "")
    if schoon == "":
        return None
    if "," in schoon:
        schoon = schoon.replace(".", "").replace(",", ".")
    try:
        return float(schoon)
    except ValueError:
        return None
