"""Jaarkalender: de startpagina na inloggen (Excel-blad 'Kalender')."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..services import instellingen, klok
from ..services.kalender import week_van
from ..services.overzichten import jaarkalender, roostervrije_dagen, uren_overzicht, weken_lijst
from ..services.tijden import parse_datum

bp = Blueprint("kalender", __name__, url_prefix="/kalender")


def kies_jaar() -> int:
    """Jaar uit ?jaar=, anders het huidige jaar (binnen redelijke grenzen)."""
    jaar = request.args.get("jaar", type=int) or klok.vandaag().year
    return min(max(jaar, 1950), 2150)


@bp.route("/")
@login_required
def jaar():
    gekozen = kies_jaar()
    return render_template(
        "kalender/jaar.html",
        jaar=gekozen,
        maanden=jaarkalender(gekozen),
        weken=weken_lijst(gekozen),
        overzicht=uren_overzicht(gekozen),
        feestdagen=roostervrije_dagen(gekozen),
        laatst_bijgewerkt=instellingen.lees("laatst_bijgewerkt"),
        huidige_week=week_van(klok.vandaag()),
        deel_token=None,
    )


@bp.route("/zoek")
@login_required
def zoek_datum():
    """'Zoek datum': dd-mm (gekozen jaar) of dd-mm-jjjj -> juiste week, dag gemarkeerd."""
    datum = parse_datum(request.args.get("datum", ""), standaard_jaar=kies_jaar())
    if datum is None:
        flash("Gebruik het formaat dd-mm of dd-mm-jjjj.", "fout")
        return redirect(url_for("kalender.jaar", jaar=kies_jaar()))
    iso_jaar, week = week_van(datum)
    return redirect(url_for("rooster.week_tonen", jaar=iso_jaar, week=week, dag=datum.isoformat()))
