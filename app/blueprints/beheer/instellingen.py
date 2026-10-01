"""Algemene instellingen, toeslagen en 'alle uren herberekenen'."""

import secrets

from flask import flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Dienst, Dienstcode, Medewerker
from ...services import instellingen, klok, logboek, sync_planning
from ...services.rooster import herbereken_alle
from ...services.tijden import is_cijfers
from ...services.validatie import MAX_GETAL
from ..hulp import MAX_FACTOR, beheerder_vereist, factor, vinkje
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
        if nieuw["tijdzone"] and not klok.is_geldige_tijdzone(nieuw["tijdzone"]):
            fouten.append(f"Onbekende tijdzone '{nieuw['tijdzone']}'. Gebruik een naam zoals "
                          "Europe/Amsterdam.")

        for veld, (minimum, maximum) in GETALVELDEN.items():
            tekst = formulier.get(veld, "").strip()
            if not is_cijfers(tekst.removeprefix("-")) or not (minimum <= int(tekst) <= maximum):
                fouten.append(f"Ongeldige waarde voor '{veld}' ({minimum} t/m {maximum}).")
            else:
                nieuw[veld] = tekst

        blanco = formulier.get("blanco_code", "").strip()
        if blanco and (not is_cijfers(blanco) or int(blanco) > MAX_GETAL):
            fouten.append("De blanco-code moet een getal zijn (of leeg).")
        elif blanco and Dienstcode.query.filter_by(nummer=int(blanco)).first():
            fouten.append(f"De blanco-code {blanco} is al een dienstcode. Kies een ander nummer, "
                          "anders is die dienstcode niet meer in te voeren.")
        nieuw["blanco_code"] = blanco

        # Toeslagen: komma of punt, groter dan 0 en hooguit MAX_FACTOR
        for veld in ("toeslag_zaterdag", "toeslag_zondag"):
            waarde = factor(formulier.get(veld))
            if waarde is None:
                fouten.append(f"Toeslagfactoren moeten groter dan 0 en hooguit {MAX_FACTOR:g} zijn.")
            else:
                nieuw[veld] = str(waarde)
        if vinkje(formulier, "feestdagtoeslag_aan"):
            waarde = factor(formulier.get("toeslag_feestdag"))
            if waarde is None:
                fouten.append(f"Vul een geldige feestdagfactor in (groter dan 0, hooguit {MAX_FACTOR:g}).")
            else:
                nieuw["toeslag_feestdag"] = str(waarde)
        else:
            nieuw["toeslag_feestdag"] = ""

        nieuw["opmerkingtijden_meetellen"] = "1" if vinkje(formulier, "opmerkingtijden_meetellen") else "0"
        # Pauze: alleen als het blok in het formulier stond (een ouder formulier laat hem ongemoeid)
        pauze_nieuw = None
        if formulier.get("pauze_formulier"):
            pauze_nieuw, pauze_fouten = instellingen.controleer_pauze(
                vinkje(formulier, "pauze_aan"),
                [(formulier.get(f"pauze_grens_{i}", ""), formulier.get(f"pauze_aftrek_{i}", ""))
                 for i in range(1, instellingen.MAX_PAUZEREGELS + 1)])
            fouten += pauze_fouten
        nieuw["deellink_actief"] = "1" if vinkje(formulier, "deellink_actief") else "0"

        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/instellingen.html", w={**_huidig(), **nieuw},
                                   pauze=_pauze_formulier(formulier)), 400

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
        oude_pauze = instellingen.pauze_instelling()
        if pauze_nieuw is not None and pauze_nieuw != oude_pauze:
            logboek.log("Instelling gewijzigd", veld="pauze", oud=instellingen.pauze_tekst(oude_pauze),
                        nieuw=instellingen.pauze_tekst(pauze_nieuw))
            instellingen.schrijf("pauze", instellingen.pauze_json(pauze_nieuw["aan"], pauze_nieuw["regels"]))
            uren_gewijzigd = True
        db.session.commit()
        klok.wis_cache()  # nieuwe tijdzone direct gebruiken
        # Titel of tijdzone van afspraken gewijzigd: alle gekoppelde agenda's bijwerken
        if any(instellingen.lees(k) != oude.get(k) for k in ("agenda_voorvoegsel", "tijdzone")):
            for medewerker in Medewerker.query.filter(Medewerker.agenda_modus != "").all():
                sync_planning.plan_volledig(medewerker)
        flash("Instellingen opgeslagen.", "succes")
        if uren_gewijzigd:
            flash("Je hebt iets gewijzigd dat de uren beïnvloedt. Bestaande uren zijn nog niet "
                  "aangepast: gebruik 'Alle uren herberekenen' als dat de bedoeling is.", "info")
        return redirect(url_for("beheer.instellingen_scherm"))
    return render_template("beheer/instellingen.html", w=_huidig(), pauze=_pauze_formulier())


def _pauze_formulier(formulier=None) -> dict:
    """Het blok 'Pauze': aan/uit en MAX_PAUZEREGELS regels (grens, aftrek) als tekst."""
    if formulier is not None and formulier.get("pauze_formulier"):  # na een fout: wat er ingevuld was
        regels = [(formulier.get(f"pauze_grens_{i}", ""), formulier.get(f"pauze_aftrek_{i}", ""))
                  for i in range(1, instellingen.MAX_PAUZEREGELS + 1)]
        return {"aan": vinkje(formulier, "pauze_aan"), "regels": regels}
    instelling = instellingen.pauze_instelling()
    regels = [(f"{g:g}".replace(".", ","), f"{a:g}".replace(".", ",")) for g, a in instelling["regels"]]
    regels += [("", "")] * (instellingen.MAX_PAUZEREGELS - len(regels))
    return {"aan": instelling["aan"], "regels": regels}


def _huidig() -> dict:
    waarden = {sleutel: instellingen.lees(sleutel) for sleutel in instellingen.STANDAARD}
    waarden["tijdzone"] = waarden["tijdzone"] or klok.standaard_tijdzone()
    return waarden


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
