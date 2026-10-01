"""Logboek: elke wijziging vastleggen, en oude regels opruimen."""

from datetime import date, datetime, timedelta

from flask import has_request_context
from flask_login import current_user

from ..extensions import db
from ..models import Logboek, LoginPoging
from . import instellingen, klok
from .kalender import week_van

MAX_TEKST = 1000  # details, oude en nieuwe waarde


def _kap(waarde, lengte: int) -> str:
    """Tekst afkappen op een maximale lengte (SQLite handhaaft String(n) zelf niet)."""
    tekst = "" if waarde is None else str(waarde)
    return tekst if len(tekst) <= lengte else tekst[: lengte - 1] + "…"


def _huidige_gebruiker() -> tuple[str, str]:
    """(gebruikersnaam, rol) van wie nu ingelogd is, of ('systeem', '')."""
    if has_request_context() and current_user and current_user.is_authenticated:
        return current_user.gebruikersnaam, current_user.rol
    return "systeem", ""


def log(
    actie: str,
    details: str = "",
    *,
    datum: date | None = None,
    medewerker: str = "",
    veld: str = "",
    oud="",
    nieuw="",
    gebruiker: str | None = None,
    rol: str | None = None,
) -> None:
    """Voeg een regel toe aan het logboek. Commit doet de aanroeper.

    datum: de roosterdag waar het over gaat (week en dag worden daaruit afgeleid).
    Alle velden worden hier begrensd, zodat niemand het logboek met enorme teksten
    kan vullen (bijv. via een extreem lange gebruikersnaam bij het inloggen).
    """
    naam, huidige_rol = _huidige_gebruiker()
    week = ""
    dag = ""
    if datum is not None:
        jaar, weeknr = week_van(datum)
        week = f"{jaar}-W{weeknr:02d}"
        dag = datum.strftime("%d-%m-%Y")
    db.session.add(
        Logboek(
            gebruiker=_kap(gebruiker if gebruiker is not None else naam, 64),
            rol=_kap(rol if rol is not None else huidige_rol, 20),
            actie=_kap(actie, 60),
            details=_kap(details, MAX_TEKST),
            week=week,
            medewerker=_kap(medewerker, 120),
            dag=dag,
            veld=_kap(veld, 40),
            oude_waarde=_kap(oud, MAX_TEKST),
            nieuwe_waarde=_kap(nieuw, MAX_TEKST),
        )
    )


def opschonen(nu: datetime | None = None) -> int:
    """Verwijder regels ouder dan de bewaartermijn (dagen + uren). Geeft het aantal terug."""
    nu = nu or klok.nu()
    dagen = max(instellingen.lees_int("logboek_dagen", 31), 0)
    uren = instellingen.lees_int("logboek_uren", 0)
    if uren < 0 or uren > 23:  # zelfde grenzen als in Excel
        uren = 0
    grens = nu - timedelta(days=dagen, hours=uren)
    aantal = Logboek.query.filter(Logboek.tijdstempel < grens).delete()
    db.session.commit()
    return aantal


def ruim_loginpogingen_op() -> int:
    """Verwijder loginpogingen ouder dan één dag (die tellen niet meer mee voor de blokkade)."""
    grens = klok.utc_nu() - timedelta(days=1)
    aantal = LoginPoging.query.filter(LoginPoging.tijdstip < grens).delete()
    db.session.commit()
    return aantal
