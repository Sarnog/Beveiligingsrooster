"""Beheer: importeren uit het oude Excel-bestand (.xlsm).

Stap 1: bestand uploaden -> droogloop met voorbeeld (er wordt nog niets opgeslagen).
Stap 2: bevestigen -> definitief importeren. Het bestand wordt daarna verwijderd.
"""

import logging
import os
import secrets

from flask import flash, redirect, render_template, request, session, url_for

from ...services import backup
from ...services.excel_import import ImportFout, import_map, importeer, lees_bestand
from ..hulp import beheerder_vereist, vinkje
from . import bp

TOEGESTAAN = (".xlsm", ".xlsx")
log = logging.getLogger(__name__)


def _opgeslagen_pad() -> str | None:
    naam = session.get("import_bestand", "")
    if not naam or "/" in naam or "\\" in naam:
        return None
    pad = os.path.join(import_map(), naam)
    return pad if os.path.exists(pad) else None


def _ruim_op() -> None:
    pad = _opgeslagen_pad()
    if pad:
        os.remove(pad)
    session.pop("import_bestand", None)


@bp.route("/importeren", methods=["GET", "POST"])
@beheerder_vereist
def excel_import():
    if request.method == "POST":
        bestand = request.files.get("bestand")
        if not bestand or not bestand.filename.lower().endswith(TOEGESTAAN):
            flash("Kies een Excel-bestand (.xlsm of .xlsx).", "fout")
            return redirect(url_for("beheer.excel_import"))
        _ruim_op()
        naam = secrets.token_hex(8) + ".xlsm"
        pad = os.path.join(import_map(), naam)
        bestand.save(pad)
        os.chmod(pad, 0o600)
        session["import_bestand"] = naam
        return redirect(url_for("beheer.excel_import_voorbeeld"))
    return render_template("beheer/importeren.html", plan=None)


@bp.route("/importeren/voorbeeld", methods=["GET", "POST"])
@beheerder_vereist
def excel_import_voorbeeld():
    pad = _opgeslagen_pad()
    if pad is None:
        flash("Upload eerst een bestand.", "info")
        return redirect(url_for("beheer.excel_import"))
    try:
        plan = lees_bestand(pad)
    except ImportFout as fout:
        _ruim_op()
        flash(str(fout), "fout")
        return redirect(url_for("beheer.excel_import"))

    if request.method == "POST":
        if not vinkje(request.form, "bevestig"):
            flash("Vink eerst de bevestiging aan.", "fout")
        else:
            try:
                backup.maak_backup("voor-import")  # altijd eerst een back-up
                resultaat = importeer(plan)
            except ImportFout as fout:
                flash(str(fout), "fout")
                return redirect(url_for("beheer.excel_import_voorbeeld"))
            except Exception as fout:  # noqa: BLE001 - nooit een kale foutpagina
                log.exception("Excel-import mislukt")
                flash(f"De import is mislukt; er is niets geïmporteerd ({type(fout).__name__}).", "fout")
                return redirect(url_for("beheer.excel_import_voorbeeld"))
            _ruim_op()
            flash("Import klaar: " + ", ".join(f"{v} {k}" for k, v in resultaat.items())
                  + ". Er is vooraf een back-up gemaakt.", "succes")
            return redirect(url_for("kalender.jaar", jaar=plan.jaar))

    return render_template("beheer/importeren.html", plan=plan,
                           handmatige_uren=plan.handmatige_uren(),
                           week_verschillen=plan.weektotaal_verschillen())


@bp.route("/importeren/annuleren", methods=["POST"])
@beheerder_vereist
def excel_import_annuleren():
    _ruim_op()
    flash("Import geannuleerd; het bestand is verwijderd.", "info")
    return redirect(url_for("beheer.excel_import"))
