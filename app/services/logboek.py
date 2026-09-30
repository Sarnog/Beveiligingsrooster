"""Logboek: elke wijziging vastleggen, en oude regels opruimen."""

from datetime import date, datetime, timedelta

from flask import has_request_context
from flask_login import current_user

from ..extensions import db
from ..models import Logboek
from . import instellingen, klok
from .kalender import week_van


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
            gebruiker=gebruiker if gebruiker is not None else naam,
            rol=rol if rol is not None else huidige_rol,
            actie=actie,
            details=details,
            week=week,
            medewerker=medewerker,
            dag=dag,
            veld=veld,
            oude_waarde="" if oud is None else str(oud),
            nieuwe_waarde="" if nieuw is None else str(nieuw),
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
