"""Gedeelde invoercontroles: Beheer, de setup-wizard, de command line en de Excel-import.

Eén plek voor de regels, zodat een gebruikersnaam of initialen overal hetzelfde
gecontroleerd worden. SQLite handhaaft de lengte van String(n) zelf niet; daarom
staan ook de maximale lengtes hier.
"""

import re

GEBRUIKERSNAAM_PATROON = re.compile(r"^[a-z0-9._-]{2,64}$")
INITIALEN_PATROON = re.compile(r"^[A-Z0-9]{1,10}$")
MAX_NAAM = 120  # naam van een medewerker, weergavenaam, functie/opmerking
MAX_OMSCHRIJVING = 60  # omschrijving van een dienstcode, vrije dienstnaam
MAX_GETAL = 2**31 - 1  # grootste geheel getal dat we accepteren (SQLite/JSON-veilig)


def gebruikersnaam_fout(naam: str) -> str | None:
    """Foutmelding voor een ongeldige gebruikersnaam (al in kleine letters), of None."""
    if not GEBRUIKERSNAAM_PATROON.match(naam or ""):
        return "Gebruikersnaam: 2-64 tekens, alleen a-z, 0-9, punt, streepje of underscore."
    return None


def initialen_fout(initialen: str) -> str | None:
    if not INITIALEN_PATROON.match(initialen or ""):
        return "Initialen: alleen letters en cijfers, maximaal 10 tekens."
    return None


def lengte_fout(tekst: str, maximum: int, wat: str) -> str | None:
    """Foutmelding als de tekst langer is dan maximum tekens, anders None."""
    if len(tekst or "") > maximum:
        return f"{wat}: maximaal {maximum} tekens."
    return None


def is_codenummer(nummer: int) -> bool:
    """Een dienstcodenummer is een positief geheel getal (en niet absurd groot)."""
    return 1 <= nummer <= MAX_GETAL
