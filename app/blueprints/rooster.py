"""Weekrooster: bekijken (iedereen) en invullen (beheerder), plus 'Mijn rooster'."""

import re
from datetime import date, timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import MAX_DIENSTEN_PER_DAG, Dienstcode, Medewerker
from ..services import instellingen, klok
from ..services.kalender import MAX_JAAR, MIN_JAAR, aantal_weken, maandag_van_week, week_van
from ..services.validatie import MAX_GETAL
from ..services.weekrooster import (
    VELDEN,
    VersieConflict,
    Wijziging,
    komende_diensten,
    kopieer_week,
    verwerk_rooster,
    week_gegevens,
)
from .hulp import begrensd_getal, beheerder_vereist, externe_url

bp = Blueprint("rooster", __name__)


def geldige_week(jaar: int, week: int) -> bool:
    return 1900 < jaar < 2200 and 1 <= week <= aantal_weken(jaar)


def _lees_getal(waarde, minimum: int = 0) -> int:
    """Geheel getal uit de JSON (ID of versie), minimum t/m 2^31-1 (anders ValueError)."""
    if isinstance(waarde, bool) or not isinstance(waarde, (int, str)):
        raise ValueError("geen geheel getal")
    getal = int(waarde)
    if not minimum <= getal <= MAX_GETAL:
        raise ValueError("getal buiten bereik")
    return getal


def _lees_datum(waarde) -> date:
    """ISO-datum uit het verzoek, alleen binnen MIN_JAAR..MAX_JAAR (anders ValueError)."""
    datum = date.fromisoformat(str(waarde))
    if not MIN_JAAR <= datum.year <= MAX_JAAR:
        raise ValueError("datum buiten bereik")
    return datum


@bp.route("/week")
@login_required
def week():
    """Zonder jaar/week: de huidige week (of de week van ?dag=jjjj-mm-dd)."""
    dag = request.args.get("dag")
    try:
        datum = date.fromisoformat(dag) if dag else klok.vandaag()
    except ValueError:
        datum = klok.vandaag()
    jaar, weeknr = week_van(datum)
    return redirect(url_for("rooster.week_tonen", jaar=jaar, week=weeknr, dag=dag))


@bp.route("/week/<int:jaar>/<int:week>")
@login_required
def week_tonen(jaar: int, week: int):
    if not geldige_week(jaar, week):
        abort(404)
    gegevens = week_gegevens(jaar, week)
    codes = Dienstcode.query.filter_by(actief=True).order_by(Dienstcode.nummer).all()
    return render_template(
        "rooster/week.html",
        **gegevens,
        codes=codes,
        bewerken=current_user.is_beheerder,
        markeer_dag=request.args.get("dag", ""),
        blanco=instellingen.blanco_code(),
        **navigatie(jaar, week),
    )


def navigatie(jaar: int, week: int) -> dict:
    """Vorige/volgende week (ook over de jaargrens) en de huidige week."""
    maandag = maandag_van_week(jaar, week)
    vorige = week_van(maandag - timedelta(days=7))
    volgende = week_van(maandag + timedelta(days=7))
    return {
        "vorige": vorige,
        "volgende": volgende,
        "huidig": week_van(klok.vandaag()),
        "aantal": aantal_weken(jaar),
        "vandaag": klok.vandaag(),
    }


@bp.route("/mijn")
@login_required
def mijn():
    """'Mijn rooster': de komende diensten van de gekoppelde medewerker."""
    medewerker = current_user.medewerker
    if medewerker is None:
        flash("Je account is niet gekoppeld aan een medewerker. Vraag dit aan de beheerder.", "info")
        return redirect(url_for("kalender.jaar"))
    diensten = komende_diensten(medewerker, weken=8)
    vandaag = klok.vandaag()
    # Bovenaan: de dienst van vandaag en de eerstvolgende dienst daarna
    diensten_vandaag = [d for d in diensten if d.datum == vandaag]
    volgende = next((d for d in diensten if d.datum > vandaag), None)
    # Op de dag van de volgende dienst kunnen twee diensten staan: allebei tonen
    diensten_volgende = [d for d in diensten if volgende and d.datum == volgende.datum]
    # 'Toevoegen aan mijn agenda': de ICS-link als webcal:// (opent de agenda-app),
    # zonder ICS-link naar de uitlegpagina
    if medewerker.ics_token:
        agenda_url = re.sub(r"^https?://", "webcal://", externe_url("ics.feed", token=medewerker.ics_token))
    else:
        agenda_url = url_for("rooster.agenda_info")
    return render_template("rooster/mijn.html", medewerker=medewerker, diensten=diensten,
                           vandaag=vandaag, diensten_vandaag=diensten_vandaag, volgende=volgende,
                           diensten_volgende=diensten_volgende,
                           agenda_url=agenda_url)


@bp.route("/mijn/agenda")
@login_required
def agenda_info():
    """Uitleg voor de collega: hoe krijg ik mijn diensten in mijn eigen agenda?"""
    medewerker = current_user.medewerker
    if medewerker is None:
        flash("Je account is niet gekoppeld aan een medewerker.", "info")
        return redirect(url_for("kalender.jaar"))
    ics_url = externe_url("ics.feed", token=medewerker.ics_token) if medewerker.ics_token else ""
    return render_template("rooster/agenda_info.html", medewerker=medewerker, ics_url=ics_url)


# ---------------------------------------------------------------------------
# API voor het raster (alleen beheerder). Antwoorden altijd in JSON.
# ---------------------------------------------------------------------------

@bp.route("/api/cellen", methods=["POST"])
@beheerder_vereist
def api_cellen():
    """Wijzigingen in het rooster verwerken: als voorbeeld of definitief opslaan.

    Body (JSON):
      wijzigingen:    [{mw, datum, veld, waarde, versie, volgnummer, versie2}]
                      volgnummer: 1 (standaard) of 2 = tweede dienst van die dag.
                      veld 'code' met volgnummer 1 is de cel uit het code-raster
                      ('4' of '4/7'); versie2 is dan de versie van dienst 2.
      dagopmerkingen: [{datum, tekst}]
      opslaan:        alleen bij precies true wordt er bewaard (knop 'Opslaan');
                      anders wordt alleen een voorbeeld berekend en niets opgeslagen
      ook_tonen:      ["<mw>|<datum>", ...]  extra dagen om de actuele stand van te krijgen
      ook_dagen:      ["<datum>", ...]       idem voor dagopmerkingen
    """
    gegevens = request.get_json(silent=True)
    if gegevens is None:
        gegevens = {}
    if not isinstance(gegevens, dict):
        return jsonify(fout="Geen geldige wijzigingen ontvangen."), 400
    ruwe = gegevens.get("wijzigingen") or []
    ruwe_dagen = gegevens.get("dagopmerkingen") or []
    if not isinstance(ruwe, list) or not isinstance(ruwe_dagen, list) \
            or len(ruwe) + len(ruwe_dagen) > 5000:
        return jsonify(fout="Geen geldige wijzigingen ontvangen."), 400

    try:
        wijzigingen = []
        for item in ruwe:
            veld = str(item["veld"])
            if veld not in VELDEN:
                raise ValueError
            versie = item.get("versie")
            versie2 = item.get("versie2")
            volgnummer = int(item.get("volgnummer") or 1)
            if volgnummer not in range(1, MAX_DIENSTEN_PER_DAG + 1):
                raise ValueError
            wijzigingen.append(Wijziging(
                medewerker_id=_lees_getal(item["mw"], 1),
                datum=_lees_datum(item["datum"]),
                veld=veld,
                waarde="" if item.get("waarde") is None else str(item["waarde"]),
                versie=None if versie is None else _lees_getal(versie),
                volgnummer=volgnummer,
                versie2=None if versie2 is None else _lees_getal(versie2),
            ))
        dag_wijzigingen = [(_lees_datum(d["datum"]), str(d.get("tekst") or ""))
                           for d in ruwe_dagen]
        ook_tonen = []
        for sleutel in gegevens.get("ook_tonen") or []:
            mw, datum = str(sleutel).split("|")
            ook_tonen.append((_lees_getal(mw, 1), _lees_datum(datum)))
        ook_dagen = [_lees_datum(d) for d in gegevens.get("ook_dagen") or []]
    except (KeyError, TypeError, ValueError, AttributeError):
        return jsonify(fout="Ongeldige wijziging in het verzoek."), 400

    try:
        resultaat = verwerk_rooster(wijzigingen, dag_wijzigingen,
                                    opslaan=gegevens.get("opslaan") is True,
                                    ook_tonen=ook_tonen, ook_dagen=ook_dagen)
    except VersieConflict as fout:
        return jsonify(fout=str(fout)), 409
    return jsonify(resultaat)


@bp.route("/week/<int:jaar>/<int:week>/kopieer", methods=["POST"])
@beheerder_vereist
def week_kopieren(jaar: int, week: int):
    """'Week kopiëren naar…': hele week of één medewerker naar een andere week."""
    if not geldige_week(jaar, week):
        abort(404)
    doel = request.form.get("naar", "")  # formaat van <input type="week">: 2026-W14
    try:
        doel_jaar, doel_week = doel.split("-W")
        doel_jaar, doel_week = int(doel_jaar), int(doel_week)
    except ValueError:
        flash("Kies een geldige doelweek.", "fout")
        return redirect(url_for("rooster.week_tonen", jaar=jaar, week=week))
    if not geldige_week(doel_jaar, doel_week) or (doel_jaar, doel_week) == (jaar, week):
        flash("Kies een andere, geldige doelweek.", "fout")
        return redirect(url_for("rooster.week_tonen", jaar=jaar, week=week))

    medewerker_id = request.form.get("medewerker_id", type=begrensd_getal) or None
    if request.form.get("medewerker_id") and medewerker_id is None:
        abort(404)  # onzin of een te groot getal
    if medewerker_id and db.session.get(Medewerker, medewerker_id) is None:
        abort(404)
    aantal = kopieer_week(maandag_van_week(jaar, week), maandag_van_week(doel_jaar, doel_week),
                          medewerker_id)
    flash(f"Week {week} gekopieerd naar week {doel_week} ({aantal} dagen bijgewerkt).", "succes")
    return redirect(url_for("rooster.week_tonen", jaar=doel_jaar, week=doel_week))
