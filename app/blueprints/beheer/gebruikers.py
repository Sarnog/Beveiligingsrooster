"""Beheer van gebruikersaccounts (vervangt de Excel-bladen Rechten en Beveiliging)."""

import secrets

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user

from ...extensions import db
from ...models import ROL_BEHEERDER, ROL_GEBRUIKER, Gebruiker, Medewerker
from ...services import logboek
from ...services.validatie import MAX_NAAM, gebruikersnaam_fout, lengte_fout
from ...services.wachtwoorden import hash_wachtwoord, wachtwoord_fout
from ..hulp import begrensd_getal, beheerder_vereist, vinkje
from . import bp


def _aantal_actieve_beheerders(behalve_id: int | None = None) -> int:
    query = Gebruiker.query.filter_by(rol=ROL_BEHEERDER, actief=True)
    if behalve_id is not None:
        query = query.filter(Gebruiker.id != behalve_id)
    return query.count()


def _medewerkers():
    return Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()


@bp.route("/gebruikers")
@beheerder_vereist
def gebruikers():
    lijst = Gebruiker.query.order_by(Gebruiker.gebruikersnaam).all()
    return render_template("beheer/gebruikers.html", gebruikers=lijst)


def _lees_formulier(gebruiker: Gebruiker | None) -> tuple[dict, list[str]]:
    formulier = request.form
    fouten = []
    gebruikersnaam = formulier.get("gebruikersnaam", "").strip().lower()
    if fout := gebruikersnaam_fout(gebruikersnaam):
        fouten.append(fout)
    else:
        bestaand = Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).first()
        if bestaand and (gebruiker is None or bestaand.id != gebruiker.id):
            fouten.append("Deze gebruikersnaam bestaat al.")
    weergavenaam = formulier.get("weergavenaam", "").strip()
    if not weergavenaam:
        fouten.append("Vul een weergavenaam in.")
    elif fout := lengte_fout(weergavenaam, MAX_NAAM, "Weergavenaam"):
        fouten.append(fout)
    rol = formulier.get("rol", ROL_GEBRUIKER)
    if rol not in (ROL_BEHEERDER, ROL_GEBRUIKER):
        fouten.append("Ongeldige rol.")
    medewerker_id = formulier.get("medewerker_id", type=begrensd_getal) or None
    if (formulier.get("medewerker_id") and medewerker_id is None) or (
            medewerker_id and db.session.get(Medewerker, medewerker_id) is None):
        fouten.append("Onbekende medewerker.")
    return {
        "gebruikersnaam": gebruikersnaam,
        "weergavenaam": weergavenaam,
        "rol": rol,
        "medewerker_id": medewerker_id,
        "actief": vinkje(formulier, "actief"),
    }, fouten


@bp.route("/gebruikers/nieuw", methods=["GET", "POST"])
@beheerder_vereist
def gebruiker_nieuw():
    if request.method == "POST":
        waarden, fouten = _lees_formulier(None)
        wachtwoord = request.form.get("wachtwoord", "")
        if fout := wachtwoord_fout(wachtwoord):
            fouten.append(fout)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/gebruiker_form.html", g=None, w=waarden,
                                   medewerkers=_medewerkers()), 400
        gebruiker = Gebruiker(
            **waarden,
            wachtwoord_hash=hash_wachtwoord(wachtwoord),
            moet_wachtwoord_wijzigen=True,  # eerste login: zelf een wachtwoord kiezen
        )
        db.session.add(gebruiker)
        logboek.log("Account aangemaakt", f"Rol: {gebruiker.rol}", nieuw=gebruiker.gebruikersnaam)
        db.session.commit()
        flash(f"Account {gebruiker.gebruikersnaam} aangemaakt. Bij de eerste login moet "
              "een nieuw wachtwoord gekozen worden.", "succes")
        return redirect(url_for("beheer.gebruikers"))
    return render_template("beheer/gebruiker_form.html", g=None,
                           w={"rol": ROL_GEBRUIKER, "actief": True}, medewerkers=_medewerkers())


@bp.route("/gebruikers/<int:gid>", methods=["GET", "POST"])
@beheerder_vereist
def gebruiker_bewerk(gid: int):
    gebruiker = db.get_or_404(Gebruiker, gid)
    if request.method == "POST":
        waarden, fouten = _lees_formulier(gebruiker)
        # De laatste actieve beheerder mag niet gedegradeerd of gedeactiveerd worden
        wordt_geen_beheerder = waarden["rol"] != ROL_BEHEERDER or not waarden["actief"]
        if gebruiker.is_beheerder and gebruiker.actief and wordt_geen_beheerder \
                and _aantal_actieve_beheerders(behalve_id=gebruiker.id) == 0:
            fouten.append("Dit is de laatste beheerder. Maak eerst een andere beheerder aan.")
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/gebruiker_form.html", g=gebruiker, w=waarden,
                                   medewerkers=_medewerkers()), 400
        for veld, waarde in waarden.items():
            oud = getattr(gebruiker, veld)
            if oud != waarde:
                logboek.log("Account gewijzigd", gebruiker.gebruikersnaam, veld=veld,
                            oud=oud, nieuw=waarde)
                setattr(gebruiker, veld, waarde)
                if veld in ("actief", "rol"):
                    gebruiker.maak_sessies_ongeldig()  # direct uitloggen
        db.session.commit()
        if gebruiker.id == current_user.id:
            login_user(gebruiker)  # eigen sessie geldig houden
        flash("Account opgeslagen.", "succes")
        return redirect(url_for("beheer.gebruikers"))
    waarden = {veld: getattr(gebruiker, veld)
               for veld in ("gebruikersnaam", "weergavenaam", "rol", "medewerker_id", "actief")}
    return render_template("beheer/gebruiker_form.html", g=gebruiker, w=waarden,
                           medewerkers=_medewerkers())


@bp.route("/gebruikers/<int:gid>/reset", methods=["POST"])
@beheerder_vereist
def gebruiker_reset(gid: int):
    """Wachtwoord resetten naar een tijdelijk wachtwoord (eenmalig getoond)."""
    gebruiker = db.get_or_404(Gebruiker, gid)
    tijdelijk = secrets.token_urlsafe(9)  # 12 tekens
    gebruiker.wachtwoord_hash = hash_wachtwoord(tijdelijk)
    gebruiker.moet_wachtwoord_wijzigen = True
    gebruiker.maak_sessies_ongeldig()
    logboek.log("Wachtwoord gereset", gebruiker.gebruikersnaam)
    db.session.commit()
    return render_template("beheer/gebruiker_reset.html", g=gebruiker, tijdelijk=tijdelijk)


@bp.route("/gebruikers/<int:gid>/verwijder", methods=["POST"])
@beheerder_vereist
def gebruiker_verwijder(gid: int):
    gebruiker = db.get_or_404(Gebruiker, gid)
    if gebruiker.id == current_user.id:
        flash("Je kunt je eigen account niet verwijderen.", "fout")
    elif gebruiker.is_beheerder and _aantal_actieve_beheerders(behalve_id=gebruiker.id) == 0:
        flash("De laatste beheerder kan niet verwijderd worden.", "fout")
    else:
        logboek.log("Account verwijderd", oud=gebruiker.gebruikersnaam)
        db.session.delete(gebruiker)
        db.session.commit()
        flash("Account verwijderd.", "succes")
    return redirect(url_for("beheer.gebruikers"))
