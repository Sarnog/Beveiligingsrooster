"""API voor een (toekomstige) app: /api/v1, alleen lezen, JSON.

Inloggen met een persoonlijk API-token (Authorization: Bearer br_...) of met een
gewone sessie. Rechten zijn gelijk aan die van de webpagina's. Het versienummer
staat in het pad: een wijziging die bestaande apps breekt, komt in /api/v2.
Documentatie: docs/api.md.
"""

from datetime import date, timedelta

from flask import Blueprint, abort, g, jsonify, request
from flask_login import current_user, login_required

from ..models import Dienst, Dienstcode
from ..services import klok
from ..services.kalender import MAX_JAAR, MIN_JAAR, aantal_weken
from ..services.weekrooster import week_gegevens

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

API_VERSIE = 1
MAX_DAGEN = 366  # langste periode voor mijn-rooster


def fout(melding: str, status: int):
    return jsonify(fout=melding), status


@bp.before_request
def controleer():
    current_user.is_authenticated  # noqa: B018  (laadt de gebruiker, ook via het token)
    if g.pop("api_geblokkeerd", False):
        return fout("Te veel ongeldige tokens vanaf dit adres. Probeer het over 15 minuten opnieuw.", 429)
    if current_user.is_authenticated and current_user.moet_wachtwoord_wijzigen:
        return fout("Kies eerst een nieuw wachtwoord in de website.", 403)
    return None


def dienst_json(dienst: Dienst | None) -> dict | None:
    if dienst is None:
        return None
    code = dienst.dienstcode
    return {
        "datum": dienst.datum.isoformat(),
        "code": code.nummer if code else None,
        "dienstnaam": dienst.dienstnaam,
        "begin": dienst.begin,
        "eind": dienst.eind,
        "uren": dienst.uren_berekend,
        "opmerking": dienst.opmerking_tekst or "",
        "opmerking_begin": dienst.opmerking_begin,
        "opmerking_eind": dienst.opmerking_eind,
        "kleur_achtergrond": code.kleur_achtergrond if code else None,
        "kleur_tekst": code.kleur_tekst if code else None,
    }


def medewerker_json(medewerker) -> dict | None:
    if medewerker is None:
        return None
    return {"id": medewerker.id, "naam": medewerker.naam, "initialen": medewerker.initialen}


def _datum(naam: str, standaard: date) -> date:
    waarde = request.args.get(naam)
    if not waarde:
        return standaard
    try:
        datum = date.fromisoformat(waarde)
    except ValueError:
        abort(400, f"'{naam}' moet een datum zijn als JJJJ-MM-DD.")
    if not MIN_JAAR <= datum.year <= MAX_JAAR:
        abort(400, f"'{naam}' ligt buiten {MIN_JAAR}–{MAX_JAAR}.")
    return datum


@bp.route("/ik")
@login_required
def ik():
    from .. import VERSIE

    return jsonify({
        "api_versie": API_VERSIE,
        "app_versie": VERSIE,
        "gebruiker": {"id": current_user.id, "gebruikersnaam": current_user.gebruikersnaam,
                      "weergavenaam": current_user.weergavenaam, "rol": current_user.rol},
        "medewerker": medewerker_json(current_user.medewerker),
    })


@bp.route("/mijn-rooster")
@login_required
def mijn_rooster():
    """Diensten van de gekoppelde medewerker; standaard vandaag t/m 8 weken vooruit."""
    medewerker = current_user.medewerker
    if medewerker is None:
        return fout("Je account is niet gekoppeld aan een medewerker.", 404)
    van = _datum("van", klok.vandaag())
    tot = _datum("tot", van + timedelta(weeks=8, days=-1))
    if tot < van:
        return fout("'tot' ligt vóór 'van'.", 400)
    if (tot - van).days >= MAX_DAGEN:
        return fout(f"De periode is te lang (hooguit {MAX_DAGEN} dagen).", 400)
    diensten = (Dienst.query.filter(Dienst.medewerker_id == medewerker.id, Dienst.datum >= van,
                                    Dienst.datum <= tot).order_by(Dienst.datum).all())
    return jsonify({"medewerker": medewerker_json(medewerker), "van": van.isoformat(),
                    "tot": tot.isoformat(), "diensten": [dienst_json(d) for d in diensten]})


@bp.route("/week/<int:jaar>/<int:week>")
@login_required
def week(jaar: int, week: int):
    """Het weekrooster: dezelfde gegevens en rechten als de pagina Weekrooster."""
    if not (MIN_JAAR <= jaar <= MAX_JAAR and 1 <= week <= aantal_weken(jaar)):
        return fout("Deze week bestaat niet.", 404)
    gegevens = week_gegevens(jaar, week)
    dagen = gegevens["dagen"]
    diensten = {(d.medewerker_id, d.datum): d for d in Dienst.query.filter(
        Dienst.datum >= dagen[0], Dienst.datum <= dagen[-1]).all()}
    return jsonify({
        "jaar": jaar,
        "week": week,
        "dagen": [{"datum": dag.isoformat(),
                   "dagopmerking": gegevens["dagopmerkingen"][dag]["tekst"],
                   "feestdag": gegevens["feestdagen"].get(dag)} for dag in dagen],
        "medewerkers": [{
            **medewerker_json(rij.medewerker),
            "contracturen": rij.contracturen,
            "weektotaal": round(rij.weektotaal, 2),
            "dagen": [dienst_json(diensten.get((rij.medewerker.id, dag))) for dag in dagen],
        } for rij in gegevens["rijen"]],
    })


@bp.route("/dienstcodes")
@login_required
def dienstcodes():
    codes = Dienstcode.query.filter_by(actief=True).order_by(Dienstcode.nummer).all()
    return jsonify({"dienstcodes": [{
        "nummer": c.nummer, "omschrijving": c.omschrijving, "std_begin": c.std_begin,
        "std_eind": c.std_eind, "std_uren": c.std_uren, "kleur_achtergrond": c.kleur_achtergrond,
        "kleur_tekst": c.kleur_tekst} for c in codes]})
