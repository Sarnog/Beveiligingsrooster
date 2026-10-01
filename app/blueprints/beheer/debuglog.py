"""Beheer: logniveau en debuglog instellen, de debuglog bekijken en downloaden."""

import os

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for

from ... import debuglog
from ...extensions import db
from ...services import instellingen, logboek
from ..hulp import beheerder_vereist
from . import bp

AANTAL_REGELS = 500


@bp.route("/debuglog")
@beheerder_vereist
def debuglog_scherm():
    map_ = current_app.config["DATA_MAP"]
    pad = debuglog.bestand(map_)
    niveau, aan = debuglog.effectief(current_app)
    return render_template(
        "beheer/debuglog.html", aan=aan, niveau=niveau, niveaus=debuglog.NIVEAUS,
        eigen_niveau=instellingen.lees("log_niveau"), eigen_aan=instellingen.lees("debug_log"),
        env_niveau=current_app.config["LOG_NIVEAU"], env_aan=current_app.config["DEBUG_LOG"],
        regels=debuglog.laatste_regels(map_, AANTAL_REGELS) if aan else [],
        grootte=os.path.getsize(pad) if os.path.exists(pad) else 0, aantal=AANTAL_REGELS,
    )


def _omschrijving(niveau: str, aan: str) -> str:
    """Voor het logboek, bijv. 'DEBUG, debuglog aan' of 'volgens .env, debuglog volgens .env'."""
    bestand = {"1": "aan", "0": "uit"}.get(aan, "volgens .env")
    return f"{niveau or 'volgens .env'}, debuglog {bestand}"


@bp.route("/debuglog/instellen", methods=["POST"])
@beheerder_vereist
def debuglog_instellen():
    """Logniveau en debuglog-bestand; leeg = volgens .env (LOG_NIVEAU / DEBUG_LOG)."""
    niveau = request.form.get("log_niveau", "").strip().upper()
    aan = request.form.get("debug_log", "").strip()
    if niveau not in ("",) + debuglog.NIVEAUS or aan not in ("", "0", "1"):
        flash("Ongeldige keuze.", "fout")
        return redirect(url_for("beheer.debuglog_scherm"))
    oud = _omschrijving(instellingen.lees("log_niveau"), instellingen.lees("debug_log"))
    instellingen.schrijf("log_niveau", niveau)
    instellingen.schrijf("debug_log", aan)
    nieuw = _omschrijving(niveau, aan)
    logboek.log("Loginstelling gewijzigd", oud=oud, nieuw=nieuw)
    db.session.commit()
    debuglog.ververs(current_app._get_current_object(), direct=True)  # dit proces meteen
    flash("Loginstelling opgeslagen. Binnen een halve minuut is hij overal actief "
          "(website en worker), zonder herstart.", "succes")
    return redirect(url_for("beheer.debuglog_scherm"))


@bp.route("/debuglog/download")
@beheerder_vereist
def debuglog_download():
    pad = debuglog.bestand(current_app.config["DATA_MAP"])
    if not os.path.exists(pad):
        abort(404)
    logboek.log("Debuglog gedownload")
    db.session.commit()
    return send_file(pad, as_attachment=True, download_name="debug.log", mimetype="text/plain")
