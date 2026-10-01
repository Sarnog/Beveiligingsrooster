"""Hulpfuncties voor tijden en datums in Nederlandse notatie."""

import re
from datetime import date, datetime

from . import klok


class OngeldigeTijd(ValueError):
    """Wordt gegooid als een tijd niet te lezen is."""


_CIJFERS = re.compile(r"[0-9]+")


def is_cijfers(tekst: str) -> bool:
    """True als de tekst alleen uit de cijfers 0-9 bestaat.

    Bewust niet str.isdigit(): die vindt ook '²' of Arabische cijfers goed, en daar
    kan int() niet altijd mee overweg.
    """
    return bool(_CIJFERS.fullmatch(tekst or ""))


def normaliseer_tijd(invoer: str | None) -> str | None:
    """Zet allerlei tijdnotaties om naar 'HH:MM'.

    Toegestaan: '715', '0715', '7:15', '07.15', '7', '07:15'.
    Lege invoer geeft None (geen tijd). Ongeldige invoer geeft OngeldigeTijd.
    """
    if invoer is None:
        return None
    tekst = str(invoer).strip()
    if tekst == "":
        return None

    # Scheidingsteken (':' '.' ',') vervangen door ':'
    tekst = re.sub(r"[.,;]", ":", tekst)

    if ":" in tekst:
        delen = tekst.split(":")
        if len(delen) != 2 or not is_cijfers(delen[0]) or not is_cijfers(delen[1]):
            raise OngeldigeTijd(f"Ongeldige tijd: {invoer}")
        uur, minuut = int(delen[0]), int(delen[1])
        if len(delen[1]) == 1:
            # '7:3' lezen we als 07:30, net als '7.3'
            minuut = minuut * 10
    elif is_cijfers(tekst):
        if len(tekst) <= 2:  # '7' of '07' = hele uren
            uur, minuut = int(tekst), 0
        elif len(tekst) in (3, 4):  # '715' of '0715'
            uur, minuut = int(tekst[:-2]), int(tekst[-2:])
        else:
            raise OngeldigeTijd(f"Ongeldige tijd: {invoer}")
    else:
        raise OngeldigeTijd(f"Ongeldige tijd: {invoer}")

    # 24:00 accepteren we als middernacht (00:00)
    if uur == 24 and minuut == 0:
        uur = 0
    if not (0 <= uur <= 23 and 0 <= minuut <= 59):
        raise OngeldigeTijd(f"Ongeldige tijd: {invoer}")
    return f"{uur:02d}:{minuut:02d}"


def tijd_naar_minuten(tijd: str | None) -> int | None:
    """'07:15' -> 435 minuten. None blijft None."""
    if not tijd:
        return None
    uur, minuut = tijd.split(":")
    return int(uur) * 60 + int(minuut)


def parse_datum(invoer: str | None, standaard_jaar: int | None = None) -> date | None:
    """Lees een datum als 'dd-mm-jjjj', 'dd-mm' (huidig of opgegeven jaar) of 'jjjj-mm-dd'.

    Geeft None bij lege of ongeldige invoer.
    """
    if not invoer:
        return None
    tekst = str(invoer).strip().replace("/", "-").replace(".", "-")
    try:
        # ISO-formaat uit een <input type="date">
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", tekst):
            return datetime.strptime(tekst, "%Y-%m-%d").date()
        if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}", tekst):
            return datetime.strptime(tekst, "%d-%m-%Y").date()
        if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{2}", tekst):
            return datetime.strptime(tekst, "%d-%m-%y").date()
        if re.fullmatch(r"\d{1,2}-\d{1,2}", tekst):
            jaar = standaard_jaar or klok.vandaag().year
            dag, maand = tekst.split("-")
            return date(jaar, int(maand), int(dag))
    except ValueError:
        return None
    return None


def datum_nl(datum: date | None) -> str:
    """date -> 'dd-mm-jjjj'."""
    return datum.strftime("%d-%m-%Y") if datum else ""
