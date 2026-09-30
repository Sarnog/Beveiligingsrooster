"""Algemene instellingen, toeslagen en 'alle uren herberekenen'."""

import secrets

from flask import flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Dienst, Medewerker
from ...services import instellingen, logboek, sync_planning
from ...services.rooster import herbereken_alle
from ..hulp import beheerder_vereist, getal, vinkje
from . import bp

# Tekstinstellingen die direct uit het formulier komen
TEKSTVELDEN = ("teamnaam", "tijdzone", "voettekst", "agenda_voorvoegsel")
# Gehele getallen met (minimum, maximum)
GETALVELDEN = {
    "eerste_jaar": (2000, 2100),
    "logboek_dagen": (0, 3650),
    "logboek_uren": (0, 23),
    "agenda_sync_dagen_terug": (0, 365),
    "agenda_sync_maanden_vooruit": (1, 36),
    "backup_bewaren": (1, 365),
}


@bp.route("/instellingen", methods=["GET", "POST"])
@beheerder_vereist
def instellingen_scherm():
    if request.method == "POST":
        formulier = request.form
        fouten = []
        nieuw: dict[str, str] = {}

        for veld in TEKSTVELDEN:
            nieuw[veld] = formulier.get(veld, "").strip()
        if not nieuw["teamnaam"]:
            fouten.append("Vul een teamnaam in.")

        for veld, (minimum, maximum) in GETALVELDEN.items():
            tekst = formulier.get(veld, "").strip()
            if not tekst.lstrip("-").isdigit() or not (minimum <= int(tekst) <= maximum):
                fouten.append(f"Ongeldige waarde voor '{veld}' ({minimum} t/m {maximum}).")
            else:
                nieuw[veld] = tekst

        blanco = formulier.get("blanco_code", "").strip()
        if blanco and not blanco.isdigit():
            fouten.append("De blanco-code moet een getal zijn (of leeg).")
        nieuw["blanco_code"] = blanco

        # Toeslagen: komma of punt
        for veld in ("toeslag_zaterdag", "toeslag_zondag"):
            waarde = getal(formulier.get(veld))
            if waarde is None or waarde <= 0:
                fouten.append("Toeslagfactoren moeten groter dan 0 zijn.")
            else:
                nieuw[veld] = str(waarde)
        if vinkje(formulier, "feestdagtoeslag_aan"):
            waarde = getal(formulier.get("toeslag_feestdag"))
            if waarde is None or waarde <= 0:
                fouten.append("Vul een geldige feestdagfactor in.")
            else:
                nieuw["toeslag_feestdag"] = str(waarde)
        else:
            nieuw["toeslag_feestdag"] = ""

        nieuw["opmerkingtijden_meetellen"] = "1" if vinkje(formulier, "opmerkingtijden_meetellen") else "0"
        nieuw["deellink_actief"] = "1" if vinkje(formulier, "deellink_actief") else "0"

        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/instellingen.html", w={**_huidig(), **nieuw}), 400

        # Deellink aan zonder token: token aanmaken
        if nieuw["deellink_actief"] == "1" and not instellingen.lees("deellink_token"):
            instellingen.schrijf("deellink_token", secrets.token_urlsafe(24))

        oude = _huidig()
        uren_relevant = ("toeslag_zaterdag", "toeslag_zondag", "toeslag_feestdag",
                         "opmerkingtijden_meetellen")
        uren_gewijzigd = False
        for sleutel, waarde in nieuw.items():
            oud = instellingen.lees(sleutel)
            if oud != waarde:
                logboek.log("Instelling gewijzigd", veld=sleutel, oud=oud, nieuw=waarde)
                instellingen.schrijf(sleutel, waarde)
                uren_gewijzigd = uren_gewijzigd or sleutel in uren_relevant
        db.session.commit()
        # Titel of tijdzone van afspraken gewijzigd: alle gekoppelde agenda's bijwerken
        if any(instellingen.lees(k) != oude.get(k) for k in ("agenda_voorvoegsel", "tijdzone")):
            for medewerker in Medewerker.query.filter(Medewerker.agenda_modus != "").all():
                sync_planning.plan_volledig(medewerker)
        flash("Instellingen opgeslagen.", "succes")
        if uren_gewijzigd:
            flash("Je hebt iets gewijzigd dat de uren beïnvloedt. Bestaande uren zijn nog niet "
                  "aangepast: gebruik 'Alle uren herberekenen' als dat de bedoeling is.", "info")
        return redirect(url_for("beheer.instellingen_scherm"))
    return render_template("beheer/instellingen.html", w=_huidig())


def _huidig() -> dict:
    return {sleutel: instellingen.lees(sleutel) for sleutel in instellingen.STANDAARD}


@bp.route("/instellingen/deellink-vernieuwen", methods=["POST"])
@beheerder_vereist
def deellink_vernieuwen():
    instellingen.schrijf("deellink_token", secrets.token_urlsafe(24))
    logboek.log("Deellink vernieuwd", "Oude link werkt niet meer")
    db.session.commit()
    flash("Er is een nieuwe deellink gemaakt. De oude werkt niet meer.", "succes")
    return redirect(url_for("beheer.instellingen_scherm"))


@bp.route("/herberekenen", methods=["GET", "POST"])
@beheerder_vereist
def herberekenen():
    """Alle uren opnieuw berekenen (na een wijziging van toeslagen). Met bevestiging."""
    if request.method == "POST":
        if not vinkje(request.form, "bevestig"):
            flash("Vink eerst de bevestiging aan.", "fout")
            return redirect(url_for("beheer.herberekenen"))
        gewijzigd = herbereken_alle()
        logboek.log("Uren herberekend", f"{gewijzigd} diensten gewijzigd")
        db.session.commit()
        flash(f"Klaar: bij {gewijzigd} diensten zijn de uren veranderd.", "succes")
        return redirect(url_for("beheer.index"))
    return render_template("beheer/herberekenen.html", aantal=Dienst.query.count())
