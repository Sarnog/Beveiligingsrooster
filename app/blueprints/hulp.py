"""Kleine hulpfuncties die door meerdere blueprints gebruikt worden."""

import math
import re
from functools import wraps

from flask import abort, current_app, url_for
from flask_login import current_user, login_required

KLEUR_PATROON = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_FACTOR = 10.0  # hoogste toeslagfactor die we accepteren


def beheerder_vereist(functie):
    """Decorator: alleen een ingelogde beheerder mag deze route gebruiken (anders 403)."""

    @wraps(functie)
    @login_required
    def binnen(*args, **kwargs):
        if not current_user.is_beheerder:
            abort(403)
        return functie(*args, **kwargs)

    return binnen


def externe_url(endpoint: str, **waarden) -> str:
    """Volledig adres voor buiten de app (ICS-feed, deellink).

    Met BASE_URL (bijv. https://rooster.voorbeeld.nl) wordt dat adres gebruikt; zonder
    BASE_URL het adres waarmee de pagina nu bekeken wordt.
    """
    basis = current_app.config.get("BASE_URL", "")
    if basis:
        return basis + url_for(endpoint, **waarden)
    return url_for(endpoint, _external=True, **waarden)


def kleur(waarde: str | None, standaard: str) -> str:
    """Geef een geldige #RRGGBB-kleur terug (in hoofdletters) of de standaard."""
    if waarde and KLEUR_PATROON.match(waarde.strip()):
        return waarde.strip().upper()
    return standaard


def vinkje(formulier, naam: str) -> bool:
    """True als een checkbox aangevinkt is."""
    return formulier.get(naam) in ("1", "on", "ja", "true")


def getal(tekst: str | None) -> float | None:
    """'1.659,5' / '1659,5' / '1659.5' -> 1659.5; leeg, ongeldig, inf of nan -> None."""
    if tekst is None:
        return None
    schoon = tekst.strip().replace(" ", "")
    if schoon == "":
        return None
    if "," in schoon:
        schoon = schoon.replace(".", "").replace(",", ".")
    try:
        waarde = float(schoon)
    except ValueError:
        return None
    return waarde if math.isfinite(waarde) else None


_GETAL = re.compile(r"-?[0-9]+([.,][0-9]+)?")


def begrensd_getal(tekst) -> int:
    """Geheel getal (ID, paginanummer) uit een formulier of URL: 0 t/m 2^31-1, anders ValueError.

    Te gebruiken als type= bij request.args.get/request.form.get: dan geeft een
    te groot getal gewoon de standaardwaarde, in plaats van een fout in SQLite (500).
    """
    from ..services.validatie import MAX_GETAL

    getal_ = int(tekst)
    if not 0 <= getal_ <= MAX_GETAL:
        raise ValueError("getal buiten bereik")
    return getal_


def csv_cel(waarde):
    """Tekst voor een CSV-cel die Excel nooit als formule uitvoert.

    Begint de tekst met = + - of @ (en is het geen gewoon getal), dan komt er een '
    voor. Zo kan bijvoorbeeld een medewerkersnaam als '=HYPERLINK(...)' geen kwaad.
    """
    if isinstance(waarde, str) and waarde[:1] in ("=", "+", "-", "@", "\t", "\r") \
            and not _GETAL.fullmatch(waarde):
        return "'" + waarde
    return waarde


def factor(tekst: str | None) -> float | None:
    """Een toeslagfactor: groter dan 0 en hooguit MAX_FACTOR. Anders None."""
    waarde = getal(tekst)
    if waarde is None or not 0 < waarde <= MAX_FACTOR:
        return None
    return waarde
