"""Beheer van de Google Agenda-koppeling en de ICS-feeds (alleen beheerder)."""

import re
import secrets

from flask import flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Dienst, Medewerker, SyncTaak
from ...services import google_agenda, instellingen, logboek, sync, sync_planning
from ...services.google_agenda import AgendaFout
from ..hulp import beheerder_vereist, vinkje
from . import bp

EMAIL_PATROON = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/agenda")
@beheerder_vereist
def agenda():
    medewerkers = Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()
    afspraken = dict(
        db.session.query(Dienst.medewerker_id, db.func.count(Dienst.id))
        .filter(Dienst.google_event_id != "").group_by(Dienst.medewerker_id).all()
    )
    wachtrij = dict(db.session.query(SyncTaak.status, db.func.count(SyncTaak.id))
                    .group_by(SyncTaak.status).all())
    return render_template(
        "beheer/agenda.html", medewerkers=medewerkers, afspraken=afspraken, wachtrij=wachtrij,
        sleutel=google_agenda.sleutel_aanwezig(), sa_email=google_agenda.service_account_email(),
        periode=sync.sync_periode(),
    )


def _terug():
    return redirect(url_for("beheer.agenda"))


@bp.route("/agenda/sleutel", methods=["POST"])
@beheerder_vereist
def agenda_sleutel():
    """Service-account-sleutel uploaden (of verwijderen)."""
    if request.form.get("verwijder"):
        google_agenda.verwijder_sleutel()
        logboek.log("Google-sleutel verwijderd")
        db.session.commit()
        flash("Het sleutelbestand is verwijderd.", "succes")
        return _terug()
    bestand = request.files.get("sleutel")
    if not bestand or not bestand.filename:
        flash("Kies een JSON-sleutelbestand.", "fout")
        return _terug()
    try:
        email = google_agenda.bewaar_sleutel(bestand.read())
    except ValueError as fout:
        flash(str(fout), "fout")
        return _terug()
    logboek.log("Google-sleutel geüpload", nieuw=email)
    db.session.commit()
    flash(f"Sleutel opgeslagen. Service-account: {email}", "succes")
    return _terug()


@bp.route("/agenda/<int:mid>/koppel", methods=["POST"])
@beheerder_vereist
def agenda_koppel(mid: int):
    """Modus A: agenda aanmaken en delen. Modus B: bestaande (gedeelde) agenda gebruiken."""
    medewerker = db.get_or_404(Medewerker, mid)
    modus = request.form.get("modus")
    if medewerker.agenda_modus:
        flash(f"{medewerker.naam} is al gekoppeld.", "info")
        return _terug()

    if modus == "A":
        # Het e-mailadres kan direct bij de knop ingevuld worden
        email = request.form.get("email", medewerker.email or "").strip()
        if not EMAIL_PATROON.match(email):
            flash(f"Vul een geldig e-mailadres (Google-account) in voor {medewerker.naam}.", "fout")
            return _terug()
        if email != medewerker.email:
            logboek.log("Medewerker gewijzigd", "Bij agenda koppelen", medewerker=medewerker.naam,
                        veld="email", oud=medewerker.email, nieuw=email)
            medewerker.email = email
            db.session.commit()

    try:
        klant = google_agenda.klant()
        if modus == "A":
            agenda_id = klant.maak_agenda(google_agenda.agenda_titel(medewerker),
                                          instellingen.lees("tijdzone") or "Europe/Amsterdam")
            try:
                klant.deel_agenda(agenda_id, medewerker.email)
            except AgendaFout:
                # Delen mislukt: de net gemaakte agenda weer opruimen (niet laten slingeren)
                try:
                    klant.verwijder_agenda(agenda_id)
                except AgendaFout:
                    pass
                raise
        elif modus == "B":
            agenda_id = request.form.get("agenda_id", "").strip()
            if not agenda_id:
                flash("Vul het agenda-ID in.", "fout")
                return _terug()
            klant.agenda_info(agenda_id)  # test direct of we erbij kunnen
        else:
            flash("Onbekende koppelmodus.", "fout")
            return _terug()
    except AgendaFout as fout:
        flash(f"Koppelen mislukt: {fout}", "fout")
        logboek.log("Agenda-sync fout", f"Koppelen: {fout}", medewerker=medewerker.naam)
        db.session.commit()
        return _terug()

    medewerker.agenda_modus = modus
    medewerker.agenda_id = agenda_id
    medewerker.agenda_laatste_fout = ""
    logboek.log("Agenda gekoppeld", f"Modus {modus}", medewerker=medewerker.naam, nieuw=agenda_id)
    db.session.commit()
    sync_planning.plan_volledig(medewerker)
    uitleg = (f" {medewerker.email} krijgt een uitnodiging per e-mail." if modus == "A" else "")
    flash(f"{medewerker.naam} is gekoppeld; de agenda wordt nu gevuld.{uitleg}", "succes")
    return _terug()


@bp.route("/agenda/<int:mid>/test", methods=["POST"])
@beheerder_vereist
def agenda_test(mid: int):
    medewerker = db.get_or_404(Medewerker, mid)
    try:
        info = google_agenda.klant().agenda_info(medewerker.agenda_id)
        flash(f"Koppeling werkt: agenda '{info.get('summary', medewerker.agenda_id)}' is bereikbaar.",
              "succes")
    except AgendaFout as fout:
        medewerker.agenda_laatste_fout = str(fout)
        db.session.commit()
        flash(f"Koppeling werkt niet: {fout}", "fout")
    return _terug()


@bp.route("/agenda/<int:mid>/volledig", methods=["POST"])
@beheerder_vereist
def agenda_volledig(mid: int):
    medewerker = db.get_or_404(Medewerker, mid)
    sync_planning.plan_volledig(medewerker)
    flash(f"Volledige synchronisatie voor {medewerker.naam} staat in de wachtrij.", "succes")
    return _terug()


@bp.route("/agenda/<int:mid>/ontkoppel", methods=["POST"])
@beheerder_vereist
def agenda_ontkoppel(mid: int):
    medewerker = db.get_or_404(Medewerker, mid)
    verwijder = vinkje(request.form, "verwijder")
    logboek.log("Agenda ontkoppeld", "Afspraken verwijderen" if verwijder else "Afspraken blijven staan",
                medewerker=medewerker.naam, oud=medewerker.agenda_id)
    sync_planning.plan_ontkoppel(medewerker, verwijder)
    db.session.commit()
    flash(f"{medewerker.naam} is ontkoppeld.", "succes")
    return _terug()


@bp.route("/agenda/opnieuw", methods=["POST"])
@beheerder_vereist
def agenda_opnieuw():
    aantal = sync.probeer_mislukte_opnieuw()
    flash(f"{aantal} mislukte taken worden opnieuw geprobeerd.", "succes")
    return _terug()


@bp.route("/agenda/<int:mid>/ics", methods=["POST"])
@beheerder_vereist
def agenda_ics(mid: int):
    """ICS-token aanmaken/vernieuwen of intrekken."""
    medewerker = db.get_or_404(Medewerker, mid)
    if request.form.get("intrekken"):
        medewerker.ics_token = ""
        logboek.log("ICS-feed ingetrokken", medewerker=medewerker.naam)
        flash("De ICS-link werkt niet meer.", "succes")
    else:
        medewerker.ics_token = secrets.token_urlsafe(24)
        logboek.log("ICS-feed vernieuwd", medewerker=medewerker.naam)
        flash("Nieuwe ICS-link gemaakt (een eventuele oude link werkt niet meer).", "succes")
    db.session.commit()
    return _terug()
