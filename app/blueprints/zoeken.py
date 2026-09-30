"""Zoeken naar diensten (Excel-bladen 'Zoeken' + 'DataZoek')."""

import csv
import io

from flask import Blueprint, Response, render_template, request
from flask_login import login_required

from ..models import Dienstcode
from ..services.overzichten import MIN_NAAM, zoek_diensten
from ..services.tijden import parse_datum

bp = Blueprint("zoeken", __name__, url_prefix="/zoeken")


def _lees_filters() -> tuple[dict, str | None]:
    """Lees de zoekvelden. Geeft (filters, foutmelding of None)."""
    naam = request.args.get("naam", "").strip()
    code_tekst = request.args.get("code", "").strip()
    filters = {
        "naam": naam,
        "code": int(code_tekst) if code_tekst.isdigit() else None,
        "van": parse_datum(request.args.get("van")),
        "tot": parse_datum(request.args.get("tot")),
    }
    if code_tekst and not code_tekst.isdigit():
        return filters, "De dienstcode moet een nummer zijn."
    if len(naam) < MIN_NAAM and filters["code"] is None:
        return filters, f"Vul minimaal een naam (≥ {MIN_NAAM} tekens) of een dienstcode in."
    return filters, None


@bp.route("/")
@login_required
def zoek():
    codes = Dienstcode.query.order_by(Dienstcode.nummer).all()
    resultaten, fout = None, None
    if request.args:
        filters, fout = _lees_filters()
        if not fout:
            resultaten = zoek_diensten(**filters)
    return render_template("zoeken/zoek.html", codes=codes, resultaten=resultaten, fout=fout,
                           args=request.args)


@bp.route("/export.csv")
@login_required
def export_csv():
    filters, fout = _lees_filters()
    if fout:
        return Response(fout, status=400, mimetype="text/plain; charset=utf-8")
    uitvoer = io.StringIO()
    schrijver = csv.writer(uitvoer, delimiter=";")
    schrijver.writerow(["Datum", "Week", "Initialen", "Naam", "Dienstcode", "Begin", "Eind",
                        "Dienst", "Uren", "Afwijkend"])
    for d in zoek_diensten(**filters):
        schrijver.writerow([
            d.datum.strftime("%d-%m-%Y"), d.datum.isocalendar()[1], d.medewerker.initialen,
            d.medewerker.naam, d.dienstcode.nummer if d.dienstcode else "", d.begin or "",
            d.eind or "", d.dienstnaam,
            "" if d.uren_berekend is None else f"{d.uren_berekend:.2f}".replace(".", ","),
            "ja" if d.tijden_handmatig else "",
        ])
    return Response("﻿" + uitvoer.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=zoekresultaat.csv"})
