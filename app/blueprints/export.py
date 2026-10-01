"""Rooster exporteren naar MS Excel (.xlsx): een jaar of een periode, optioneel één medewerker.

Toegang: iedereen die ingelogd is (dezelfde leesrechten als het weekrooster). Niet via de
deellink: die toont geen contracturen en weektotalen (zie deel.py), en de export wel.
"""

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..extensions import db
from ..models import Medewerker
from ..services import klok, logboek
from ..services.excel_export import ExportFout, bestandsnaam, maak_export, periode_voor
from ..services.kalender import MAX_JAAR, MIN_JAAR
from ..services.tijden import parse_datum
from .hulp import begrensd_getal

bp = Blueprint("export", __name__, url_prefix="/export")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _medewerkers():
    return Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()


@bp.route("/")
@login_required
def kiezen():
    """Keuzes voor de export (jaar of periode, medewerker)."""
    return render_template("export/kiezen.html", medewerkers=_medewerkers(), min_jaar=MIN_JAAR,
                           max_jaar=MAX_JAAR, jaar=request.args.get("jaar", type=begrensd_getal)
                           or klok.vandaag().year, args=request.args)


@bp.route("/rooster.xlsx")
@login_required
def rooster_xlsx():
    """Het .xlsx-bestand downloaden (Content-Disposition: attachment)."""
    jaar = request.args.get("jaar", type=begrensd_getal)
    van_tekst, tot_tekst = request.args.get("van", ""), request.args.get("tot", "")
    van, tot = parse_datum(van_tekst), parse_datum(tot_tekst)
    medewerker = None
    medewerker_id = request.args.get("medewerker", type=begrensd_getal)
    try:
        if (van_tekst and van is None) or (tot_tekst and tot is None):
            raise ExportFout("Vul een geldige periode in (of laat die leeg voor een heel jaar).")
        if medewerker_id:
            medewerker = db.session.get(Medewerker, medewerker_id)
            if medewerker is None:
                raise ExportFout("Onbekende medewerker.")
        iso_jaar, van, tot = periode_voor(jaar if not (van or tot) else None, van, tot)
    except ExportFout as fout:
        flash(str(fout), "fout")
        return redirect(url_for("export.kiezen", **request.args))
    inhoud = maak_export(iso_jaar, van, tot, medewerker)
    naam = bestandsnaam(iso_jaar, van, tot, medewerker)
    logboek.log("Rooster geëxporteerd", f"Excel: {van:%d-%m-%Y} t/m {tot:%d-%m-%Y}",
                medewerker=medewerker.naam if medewerker else "alle", nieuw=naam)
    db.session.commit()
    return Response(inhoud, mimetype=XLSX, headers={"Content-Disposition": f"attachment; filename={naam}"})
