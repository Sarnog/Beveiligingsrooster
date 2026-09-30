"""Beheer: back-ups maken, downloaden en terugzetten."""

import os

from flask import abort, flash, redirect, render_template, request, send_file, url_for

from ...extensions import db
from ...services import backup, klok, logboek
from ..hulp import beheerder_vereist, vinkje
from . import bp


@bp.route("/backups")
@beheerder_vereist
def backups():
    return render_template("beheer/backups.html", backups=backup.lijst_backups())


@bp.route("/backups/maken", methods=["POST"])
@beheerder_vereist
def backup_maken():
    pad = backup.maak_backup("handmatig")
    logboek.log("Back-up gemaakt", os.path.basename(pad))
    db.session.commit()
    flash(f"Back-up gemaakt: {os.path.basename(pad)}", "succes")
    return redirect(url_for("beheer.backups"))


@bp.route("/backups/download/<naam>")
@beheerder_vereist
def backup_download(naam: str):
    pad = backup.pad_van(naam)
    if pad is None:
        abort(404)
    logboek.log("Back-up gedownload", naam)
    db.session.commit()
    return send_file(pad, as_attachment=True, download_name=naam,
                     mimetype="application/vnd.sqlite3")


@bp.route("/backups/terugzetten", methods=["POST"])
@beheerder_vereist
def backup_terugzetten():
    """Een bestaande back-up (naam) of een geüpload bestand terugzetten, met bevestiging."""
    if not vinkje(request.form, "bevestig"):
        flash("Vink eerst de bevestiging aan.", "fout")
        return redirect(url_for("beheer.backups"))

    bestand = request.files.get("bestand")
    if bestand and bestand.filename:
        naam = f"rooster-{klok.nu():%Y%m%d-%H%M%S}-upload.db"
        pad = os.path.join(backup.backup_map(), naam)
        bestand.save(pad)
        os.chmod(pad, 0o600)
    else:
        naam = request.form.get("naam", "")
        pad = backup.pad_van(naam)
        if pad is None:
            flash("Onbekende back-up.", "fout")
            return redirect(url_for("beheer.backups"))

    try:
        veiligheid = backup.zet_terug(pad)
    except ValueError as fout:
        if naam.endswith("-upload.db"):
            os.remove(pad)
        flash(str(fout), "fout")
        return redirect(url_for("beheer.backups"))

    logboek.log("Back-up teruggezet", naam, oud=veiligheid)
    db.session.commit()
    flash(f"Back-up {naam} is teruggezet. De vorige stand is bewaard als {veiligheid}. "
          "Log zo nodig opnieuw in.", "succes")
    return redirect(url_for("beheer.backups"))
