"""Beheer van vakanties en feestdagen / roostervrije dagen."""


from flask import abort, flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Feestdag, Vakantie
from ...services import instellingen, logboek, sync_planning
from ...services.feestdagen import zorg_voor_jaar
from ...services.kalender import werkdagen
from ...services.tijden import parse_datum
from ..hulp import begrensd_getal, beheerder_vereist
from ..kalender import kies_jaar
from . import bp

# ---------- Vakanties ----------

@bp.route("/vakanties")
@beheerder_vereist
def vakanties():
    lijst = Vakantie.query.order_by(Vakantie.datum_van).all()
    rijen = [(v, werkdagen(v.datum_van, v.datum_tot)) for v in lijst]
    totaal = sum(aantal for _, aantal in rijen)
    return render_template("beheer/vakanties.html", rijen=rijen, totaal=totaal)


@bp.route("/vakanties/opslaan", methods=["POST"])
@beheerder_vereist
def vakantie_opslaan():
    """Nieuwe vakantie toevoegen, of een bestaande (veld 'id') wijzigen."""
    naam = request.form.get("naam", "").strip()[:80]
    van = parse_datum(request.form.get("datum_van"))
    tot = parse_datum(request.form.get("datum_tot"))
    if not naam or van is None or tot is None:
        flash("Vul een naam en twee geldige datums in.", "fout")
    elif tot < van:
        flash("De einddatum ligt voor de begindatum.", "fout")
    else:
        vid = request.form.get("id", type=begrensd_getal)
        periodes = [(van, tot)]
        if request.form.get("id") and vid is None:
            abort(404)
        if vid:
            vakantie = db.get_or_404(Vakantie, vid)
            oud = f"{vakantie.naam} {vakantie.datum_van:%d-%m-%Y} t/m {vakantie.datum_tot:%d-%m-%Y}"
            periodes.append((vakantie.datum_van, vakantie.datum_tot))
            vakantie.naam, vakantie.datum_van, vakantie.datum_tot = naam, van, tot
            actie = "Vakantie gewijzigd"
        else:
            db.session.add(Vakantie(naam=naam, datum_van=van, datum_tot=tot))
            oud = ""
            actie = "Vakantie toegevoegd"
        logboek.log(actie, oud=oud, nieuw=f"{naam} {van:%d-%m-%Y} t/m {tot:%d-%m-%Y}")
        db.session.commit()
        for begin, einde in periodes:  # de dagtekst staat in de agenda-afspraken
            sync_planning.plan_periode(begin, einde)
        flash("Vakantie opgeslagen.", "succes")
    return redirect(url_for("beheer.vakanties"))


@bp.route("/vakanties/<int:vid>/verwijder", methods=["POST"])
@beheerder_vereist
def vakantie_verwijder(vid: int):
    vakantie = db.get_or_404(Vakantie, vid)
    logboek.log("Vakantie verwijderd", oud=f"{vakantie.naam} {vakantie.datum_van:%d-%m-%Y}")
    van, tot = vakantie.datum_van, vakantie.datum_tot
    db.session.delete(vakantie)
    db.session.commit()
    sync_planning.plan_periode(van, tot)
    flash("Vakantie verwijderd.", "succes")
    return redirect(url_for("beheer.vakanties"))


# ---------- Feestdagen ----------

@bp.route("/feestdagen")
@beheerder_vereist
def feestdagen():
    jaar = kies_jaar()
    zorg_voor_jaar(jaar)
    lijst = Feestdag.query.filter_by(jaar=jaar).order_by(Feestdag.datum).all()
    return render_template("beheer/feestdagen.html", jaar=jaar, feestdagen=lijst)


@bp.route("/feestdagen/<int:fid>/wissel", methods=["POST"])
@beheerder_vereist
def feestdag_wissel(fid: int):
    """Feestdag aan- of uitzetten voor dit jaar."""
    feestdag = db.get_or_404(Feestdag, fid)
    feestdag.actief = not feestdag.actief
    logboek.log("Feestdag gewijzigd", f"{feestdag.naam} {feestdag.datum:%d-%m-%Y}",
                veld="actief", oud=not feestdag.actief, nieuw=feestdag.actief)
    db.session.commit()
    sync_planning.plan_periode(feestdag.datum, feestdag.datum)
    _herbereken_melding()
    return redirect(url_for("beheer.feestdagen", jaar=feestdag.jaar))


def _herbereken_melding() -> None:
    """Met een feestdagtoeslag veranderen de uren op die dag: herberekenen is dan nodig."""
    if instellingen.lees_float("toeslag_feestdag"):
        flash("Let op: er is een feestdagtoeslag ingesteld. Gebruik 'Alle uren herberekenen' "
              "(Beheer → Instellingen) zodat de uren op deze dag kloppen.", "info")


@bp.route("/feestdagen/nieuw", methods=["POST"])
@beheerder_vereist
def feestdag_nieuw():
    """Eigen roostervrije dag toevoegen."""
    naam = request.form.get("naam", "").strip()
    datum = parse_datum(request.form.get("datum"))
    if not naam or datum is None:
        flash("Vul een naam en een geldige datum in.", "fout")
        return redirect(url_for("beheer.feestdagen"))
    db.session.add(Feestdag(jaar=datum.year, datum=datum, naam=naam[:80], sleutel=""))
    logboek.log("Roostervrije dag toegevoegd", nieuw=f"{naam} {datum:%d-%m-%Y}")
    db.session.commit()
    sync_planning.plan_periode(datum, datum)
    flash("Roostervrije dag toegevoegd.", "succes")
    _herbereken_melding()
    return redirect(url_for("beheer.feestdagen", jaar=datum.year))


@bp.route("/feestdagen/<int:fid>/verwijder", methods=["POST"])
@beheerder_vereist
def feestdag_verwijder(fid: int):
    """Alleen eigen dagen kunnen weg; standaard feestdagen zet je uit."""
    feestdag = db.get_or_404(Feestdag, fid)
    jaar = feestdag.jaar
    if feestdag.is_eigen:
        logboek.log("Roostervrije dag verwijderd", oud=f"{feestdag.naam} {feestdag.datum:%d-%m-%Y}")
        datum = feestdag.datum
        db.session.delete(feestdag)
        db.session.commit()
        sync_planning.plan_periode(datum, datum)
        flash("Roostervrije dag verwijderd.", "succes")
        _herbereken_melding()
    else:
        flash("Standaard feestdagen kun je alleen uitzetten.", "fout")
    return redirect(url_for("beheer.feestdagen", jaar=jaar))
