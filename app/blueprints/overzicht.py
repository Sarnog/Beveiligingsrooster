"""Urenoverzicht: medewerkers x weken (Excel-blad 'UrenOverzicht')."""

import csv
import io

from flask import Blueprint, Response, render_template
from flask_login import login_required

from ..services import klok
from ..services.kalender import week_van
from ..services.overzichten import uren_overzicht, weken_lijst
from ..services.urenberekening import formatteer_uren
from .hulp import csv_cel
from .kalender import kies_jaar

bp = Blueprint("overzicht", __name__, url_prefix="/overzicht")


@bp.route("/uren")
@login_required
def uren():
    jaar = kies_jaar()
    return render_template("overzicht/uren.html", jaar=jaar, weken=weken_lijst(jaar),
                           rijen=uren_overzicht(jaar), huidige_week=week_van(klok.vandaag()))


@bp.route("/uren.csv")
@login_required
def uren_csv():
    """Hetzelfde overzicht als CSV (puntkomma's en komma's, zodat Excel het goed opent)."""
    jaar = kies_jaar()
    weken = weken_lijst(jaar)
    uitvoer = io.StringIO()
    schrijver = csv.writer(uitvoer, delimiter=";")
    schrijver.writerow(["Naam", "Initialen"] + [f"W{w}" for w in weken]
                       + ["Totaal", "Contracturen", "Verschil"])
    for rij in uren_overzicht(jaar):
        schrijver.writerow(
            [csv_cel(rij.medewerker.naam), csv_cel(rij.medewerker.initialen)]
            + [formatteer_uren(rij.per_week.get(w)) for w in weken]
            + [formatteer_uren(rij.gewerkt), formatteer_uren(rij.contracturen),
               formatteer_uren(rij.verschil)])
    return Response("﻿" + uitvoer.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=urenoverzicht-{jaar}.csv"})
