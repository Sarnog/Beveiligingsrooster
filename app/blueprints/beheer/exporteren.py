"""Beheer → Excel import/export: het rooster exporteren naar MS Excel (.xlsx).

Alleen voor de beheerder (sinds 1.6.0; daarvoor ook voor collega's onder /export/). Keuzes:
één week, een vrije periode (binnen één ISO-jaar), een heel jaar of het jaarrooster van één
persoon; bij week, periode en jaar optioneel één medewerker. Alles wordt hier opnieuw
gecontroleerd; een ongeldige keuze geeft een melding op het scherm, nooit een foutpagina.
"""

from flask import Response, flash, redirect, request, url_for

from ...extensions import db
from ...services import logboek
from ...services.excel_export import ExportFout, keuze_uit, maak_export
from ..hulp import beheerder_vereist
from . import bp

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
VELDEN = ("soort", "jaar", "week", "van", "tot", "medewerker")


@bp.route("/exporteren/rooster.xlsx")
@beheerder_vereist
def excel_export():
    """Het .xlsx-bestand downloaden (Content-Disposition: attachment)."""
    try:
        keuze = keuze_uit(request.args)
    except ExportFout as fout:
        flash(str(fout), "fout")
        # Terug naar het formulier, met de ingevulde keuzes
        terug = {f"export_{v}": request.args.get(v, "")[:20] for v in VELDEN if request.args.get(v)}
        return redirect(url_for("beheer.excel_import", **terug) + "#exporteren")
    inhoud = maak_export(keuze)
    naam = keuze.bestandsnaam
    logboek.log("Rooster geëxporteerd", f"Excel: {keuze.van:%d-%m-%Y} t/m {keuze.tot:%d-%m-%Y}",
                medewerker=keuze.medewerker.naam if keuze.medewerker else "alle", nieuw=naam)
    db.session.commit()
    return Response(inhoud, mimetype=XLSX, headers={"Content-Disposition": f"attachment; filename={naam}"})
