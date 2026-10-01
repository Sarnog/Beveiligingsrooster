"""Beheer → Statistieken: alleen-lezen overzicht (Google Agenda, back-ups, rooster, beveiliging)."""

from flask import render_template

from ...services import statistieken
from ..hulp import beheerder_vereist
from . import bp


@bp.route("/statistieken")
@beheerder_vereist
def statistieken_scherm():
    return render_template("beheer/statistieken.html", s=statistieken.verzamel(),
                           grootte=statistieken.grootte_tekst, max_dagen=statistieken.BACKUP_MAX_DAGEN)
