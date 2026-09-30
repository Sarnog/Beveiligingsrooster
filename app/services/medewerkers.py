"""Hulpfuncties voor medewerkers."""

import re

from ..models import Medewerker


def voorstel_initialen(naam: str) -> str:
    """Stel initialen voor zoals Excel dat deed.

    Eerste letter van het eerste woord + eerste 2 letters van het tweede woord,
    in hoofdletters. Voorbeeld: 'Jan Jansen' -> 'JJA'.
    Leestekens (zoals de punt in 'J. Jansen') tellen niet mee.
    """
    woorden = [re.sub(r"[^\w]", "", w) for w in naam.strip().split()]
    woorden = [w for w in woorden if w]
    if not woorden:
        return ""
    eerste = woorden[0][:1]
    tweede = woorden[1][:2] if len(woorden) > 1 else ""
    return (eerste + tweede).upper()


def uniek_voorstel(naam: str, negeer_id: int | None = None) -> str:
    """Zoals voorstel_initialen, maar met een volgnummer als de initialen al bestaan."""
    basis = voorstel_initialen(naam)
    if not basis:
        return ""
    kandidaat = basis
    teller = 2
    while True:
        bestaand = Medewerker.query.filter_by(initialen=kandidaat).first()
        if bestaand is None or bestaand.id == negeer_id:
            return kandidaat
        kandidaat = f"{basis}{teller}"
        teller += 1
