"""Beheer van medewerkers: toevoegen, wijzigen, volgorde, archiveren, verwijderen."""

import re

from flask import flash, jsonify, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Contracturen, Dienst, Gebruiker, Medewerker
from ...services import klok, logboek
from ...services.medewerkers import uniek_voorstel
from ...services.tijden import parse_datum
from ..hulp import beheerder_vereist, getal
from . import bp

EMAIL_PATROON = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _alle_medewerkers():
    return Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()


@bp.route("/medewerkers")
@beheerder_vereist
def medewerkers():
    lijst = _alle_medewerkers()
    aantallen = dict(
        db.session.query(Dienst.medewerker_id, db.func.count(Dienst.id))
        .group_by(Dienst.medewerker_id)
        .all()
    )
    return render_template(
        "beheer/medewerkers.html", medewerkers=lijst, aantallen=aantallen,
        jaar=klok.vandaag().year, vandaag=klok.vandaag(),
    )


@bp.route("/medewerkers/initialen")
@beheerder_vereist
def initialen_voorstel():
    """Live voorstel voor initialen (gebruikt door het formulier)."""
    negeer = request.args.get("id", type=int)
    return jsonify(initialen=uniek_voorstel(request.args.get("naam", ""), negeer))


def _lees_formulier(medewerker: Medewerker | None) -> tuple[dict, list[str]]:
    """Lees en controleer het formulier. Geeft (waarden, foutmeldingen)."""
    formulier = request.form
    fouten = []
    naam = formulier.get("naam", "").strip()
    initialen = formulier.get("initialen", "").strip().upper()
    email = formulier.get("email", "").strip()

    if not naam:
        fouten.append("Vul een naam in.")
    if not initialen:
        initialen = uniek_voorstel(naam, medewerker.id if medewerker else None)
    if not re.fullmatch(r"[A-Z0-9]{1,10}", initialen or ""):
        fouten.append("Initialen: alleen letters en cijfers, maximaal 10 tekens.")
    else:
        bestaand = Medewerker.query.filter_by(initialen=initialen).first()
        if bestaand and (medewerker is None or bestaand.id != medewerker.id):
            fouten.append(f"De initialen {initialen} zijn al in gebruik.")
    if email and not EMAIL_PATROON.match(email):
        fouten.append("Het e-mailadres is ongeldig.")

    # Contracturen per jaar: velden 'cu_jaar_N' en 'cu_uren_N'
    contract = {}
    for sleutel in formulier:
        if sleutel.startswith("cu_jaar_"):
            index = sleutel.removeprefix("cu_jaar_")
            jaar_tekst = formulier.get(sleutel, "").strip()
            uren_tekst = formulier.get(f"cu_uren_{index}", "").strip()
            uren = getal(uren_tekst)
            if not uren_tekst:  # geen uren ingevuld = dit jaar overslaan/verwijderen
                continue
            if not jaar_tekst.isdigit() or uren is None or uren < 0:
                fouten.append("Contracturen: vul een geldig jaar en aantal uren in.")
                continue
            contract[int(jaar_tekst)] = uren

    waarden = {
        "naam": naam,
        "initialen": initialen,
        "functie_opmerking": formulier.get("functie_opmerking", "").strip(),
        "email": email,
        "contract": contract,
    }
    return waarden, fouten


def _sla_contracturen_op(medewerker: Medewerker, contract: dict[int, float]) -> None:
    bestaande = {c.jaar: c for c in medewerker.contracturen}
    for jaar, uren in contract.items():
        if jaar in bestaande:
            if bestaande[jaar].uren != uren:
                logboek.log("Contracturen gewijzigd", str(jaar), medewerker=medewerker.naam,
                            veld="contracturen", oud=bestaande[jaar].uren, nieuw=uren)
                bestaande[jaar].uren = uren
        else:
            medewerker.contracturen.append(Contracturen(jaar=jaar, uren=uren))
            logboek.log("Contracturen gewijzigd", str(jaar), medewerker=medewerker.naam,
                        veld="contracturen", nieuw=uren)
    for jaar, rij in bestaande.items():
        if jaar not in contract:
            logboek.log("Contracturen verwijderd", str(jaar), medewerker=medewerker.naam,
                        oud=rij.uren)
            medewerker.contracturen.remove(rij)


@bp.route("/medewerkers/nieuw", methods=["GET", "POST"])
@beheerder_vereist
def medewerker_nieuw():
    if request.method == "POST":
        waarden, fouten = _lees_formulier(None)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/medewerker_form.html", m=None, w=waarden,
                                   jaar=klok.vandaag().year), 400
        hoogste = db.session.query(db.func.max(Medewerker.volgorde)).scalar() or 0
        medewerker = Medewerker(
            naam=waarden["naam"], initialen=waarden["initialen"],
            functie_opmerking=waarden["functie_opmerking"], email=waarden["email"],
            volgorde=hoogste + 1,
        )
        db.session.add(medewerker)
        _sla_contracturen_op(medewerker, waarden["contract"])
        logboek.log("Medewerker toegevoegd", medewerker=medewerker.naam, nieuw=medewerker.initialen)
        db.session.commit()
        flash(f"Medewerker {medewerker.naam} toegevoegd.", "succes")
        return redirect(url_for("beheer.medewerkers"))
    return render_template("beheer/medewerker_form.html", m=None, w={}, jaar=klok.vandaag().year)


@bp.route("/medewerkers/<int:mid>", methods=["GET", "POST"])
@beheerder_vereist
def medewerker_bewerk(mid: int):
    medewerker = db.get_or_404(Medewerker, mid)
    if request.method == "POST":
        waarden, fouten = _lees_formulier(medewerker)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/medewerker_form.html", m=medewerker, w=waarden,
                                   jaar=klok.vandaag().year), 400
        # Elke gewijzigde eigenschap apart loggen (oud -> nieuw)
        for veld in ("naam", "initialen", "functie_opmerking", "email"):
            oud = getattr(medewerker, veld)
            if oud != waarden[veld]:
                logboek.log("Medewerker gewijzigd", medewerker=medewerker.naam, veld=veld,
                            oud=oud, nieuw=waarden[veld])
                setattr(medewerker, veld, waarden[veld])
        _sla_contracturen_op(medewerker, waarden["contract"])
        db.session.commit()
        flash("Wijzigingen opgeslagen.", "succes")
        return redirect(url_for("beheer.medewerkers"))
    waarden = {
        "naam": medewerker.naam, "initialen": medewerker.initialen,
        "functie_opmerking": medewerker.functie_opmerking, "email": medewerker.email,
        "contract": {c.jaar: c.uren for c in sorted(medewerker.contracturen, key=lambda c: c.jaar)},
    }
    return render_template("beheer/medewerker_form.html", m=medewerker, w=waarden,
                           jaar=klok.vandaag().year)


@bp.route("/medewerkers/<int:mid>/verplaats", methods=["POST"])
@beheerder_vereist
def medewerker_verplaats(mid: int):
    """Volgorde: één plek omhoog of omlaag (ruilen met de buur)."""
    lijst = _alle_medewerkers()
    # Volgorde eerst netjes 1..N maken, dan ruilen
    for index, m in enumerate(lijst, start=1):
        m.volgorde = index
    positie = next((i for i, m in enumerate(lijst) if m.id == mid), None)
    if positie is None:
        return redirect(url_for("beheer.medewerkers"))
    richting = -1 if request.form.get("richting") == "omhoog" else 1
    doel = positie + richting
    if 0 <= doel < len(lijst):
        lijst[positie].volgorde, lijst[doel].volgorde = lijst[doel].volgorde, lijst[positie].volgorde
        logboek.log("Volgorde gewijzigd", medewerker=lijst[positie].naam,
                    veld="volgorde", oud=positie + 1, nieuw=doel + 1)
    db.session.commit()
    return redirect(url_for("beheer.medewerkers"))


@bp.route("/medewerkers/<int:mid>/archiveer", methods=["POST"])
@beheerder_vereist
def medewerker_archiveer(mid: int):
    medewerker = db.get_or_404(Medewerker, mid)
    if request.form.get("herstel"):
        logboek.log("Medewerker hersteld", medewerker=medewerker.naam,
                    oud=medewerker.gearchiveerd_vanaf, nieuw="")
        medewerker.gearchiveerd_vanaf = None
        flash(f"{medewerker.naam} is weer actief.", "succes")
    else:
        vanaf = parse_datum(request.form.get("vanaf")) or klok.vandaag()
        medewerker.gearchiveerd_vanaf = vanaf
        logboek.log("Medewerker gearchiveerd", medewerker=medewerker.naam,
                    veld="gearchiveerd_vanaf", nieuw=vanaf.strftime("%d-%m-%Y"))
        flash(f"{medewerker.naam} is gearchiveerd vanaf {vanaf:%d-%m-%Y}.", "succes")
    db.session.commit()
    return redirect(url_for("beheer.medewerkers"))


@bp.route("/medewerkers/<int:mid>/verwijder", methods=["GET", "POST"])
@beheerder_vereist
def medewerker_verwijder(mid: int):
    """Echt verwijderen: alleen zonder diensten, of na expliciete bevestiging."""
    medewerker = db.get_or_404(Medewerker, mid)
    aantal = Dienst.query.filter_by(medewerker_id=mid).count()
    if request.method == "POST":
        if aantal and request.form.get("bevestig") != str(aantal):
            flash("Bevestig eerst dat alle diensten ook verwijderd worden.", "fout")
            return render_template("beheer/medewerker_verwijder.html", m=medewerker, aantal=aantal), 400
        # Gekoppelde accounts losmaken
        Gebruiker.query.filter_by(medewerker_id=mid).update({"medewerker_id": None})
        Dienst.query.filter_by(medewerker_id=mid).delete()
        logboek.log("Medewerker verwijderd", f"Inclusief {aantal} diensten",
                    medewerker=medewerker.naam, oud=medewerker.initialen)
        db.session.delete(medewerker)
        db.session.commit()
        flash(f"{medewerker.naam} is verwijderd.", "succes")
        return redirect(url_for("beheer.medewerkers"))
    return render_template("beheer/medewerker_verwijder.html", m=medewerker, aantal=aantal)
