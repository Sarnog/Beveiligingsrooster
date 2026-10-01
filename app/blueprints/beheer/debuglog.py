"""Beheer: de debuglog bekijken en downloaden (alleen als DEBUG_LOG=1)."""

import os

from flask import abort, current_app, render_template, send_file

from ... import debuglog
from ...extensions import db
from ...services import logboek
from ..hulp import beheerder_vereist
from . import bp

AANTAL_REGELS = 500


@bp.route("/debuglog")
@beheerder_vereist
def debuglog_scherm():
    map_ = current_app.config["DATA_MAP"]
    pad = debuglog.bestand(map_)
    return render_template(
        "beheer/debuglog.html", aan=current_app.config["DEBUG_LOG"],
        niveau=current_app.config["LOG_NIVEAU"], regels=debuglog.laatste_regels(map_, AANTAL_REGELS),
        grootte=os.path.getsize(pad) if os.path.exists(pad) else 0, aantal=AANTAL_REGELS,
    )


@bp.route("/debuglog/download")
@beheerder_vereist
def debuglog_download():
    pad = debuglog.bestand(current_app.config["DATA_MAP"])
    if not os.path.exists(pad):
        abort(404)
    logboek.log("Debuglog gedownload")
    db.session.commit()
    return send_file(pad, as_attachment=True, download_name="debug.log", mimetype="text/plain")
