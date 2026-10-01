"""Hulpfuncties voor medewerkers."""

import re
import unicodedata

from ..models import Medewerker

_LOS = str.maketrans({"Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "ß": "ss",
                      "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Þ": "TH", "þ": "th"})


def voorstel_initialen(naam: str) -> str:
    """Stel initialen voor zoals Excel dat deed.

    Eerste letter van het eerste woord + eerste 2 letters van het tweede woord,
    in hoofdletters. Voorbeeld: 'Jan Jansen' -> 'JJA'.
    Leestekens (zoals de punt in 'J. Jansen') tellen niet mee. Letters met een accent
    worden gewone letters ('Ömer Øz' -> 'OOZ'): initialen zijn alleen A-Z en 0-9.
    """
    # Accenten weghalen (Ö -> O); wat dan nog geen A-Z/0-9 is (bijv. Ø) apart omzetten
    naam = unicodedata.normalize("NFKD", naam).translate(_LOS)
    woorden = [re.sub(r"[^A-Za-z0-9]", "", w) for w in naam.strip().split()]
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
