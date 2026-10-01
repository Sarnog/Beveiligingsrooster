"""Beheer van dienstcodes en opmerking-kleurregels."""


from flask import flash, redirect, render_template, request, url_for

from ...extensions import db
from ...models import Dienst, Dienstcode, OpmerkingKleurregel
from ...services import instellingen, klok, logboek, sync_planning
from ...services.rooster import diensten_met_afwijkende_std_tijden, pas_std_tijden_toe
from ...services.tijden import OngeldigeTijd, is_cijfers, normaliseer_tijd
from ...services.validatie import MAX_OMSCHRIJVING, is_codenummer, lengte_fout
from ...services.voorbeeldpakket import laad_voorbeeldpakket
from ...services.weekrooster import BEGIN_IS_EIND
from ..hulp import beheerder_vereist, getal, kleur, vinkje
from . import bp

MAX_KLEURREGEL = 60  # zelfde lengte als de kolom in de database
VELDEN = ("nummer", "omschrijving", "std_begin", "std_eind", "std_uren", "kleur_achtergrond",
          "kleur_tekst", "vet", "cursief", "in_agenda", "hele_dag_zonder_tijden", "actief")


@bp.route("/dienstcodes")
@beheerder_vereist
def dienstcodes():
    codes = Dienstcode.query.order_by(Dienstcode.nummer).all()
    in_gebruik = dict(
        db.session.query(Dienst.dienstcode_id, db.func.count(Dienst.id))
        .filter(Dienst.dienstcode_id.isnot(None))
        .group_by(Dienst.dienstcode_id)
        .all()
    )
    regels = OpmerkingKleurregel.query.order_by(OpmerkingKleurregel.tekst).all()
    return render_template("beheer/dienstcodes.html", codes=codes, in_gebruik=in_gebruik,
                           regels=regels, blanco=instellingen.blanco_code())


def _lees_formulier(code: Dienstcode | None) -> tuple[dict, list[str]]:
    formulier = request.form
    fouten = []
    nummer_tekst = formulier.get("nummer", "").strip()
    if not is_cijfers(nummer_tekst) or not is_codenummer(int(nummer_tekst)):
        fouten.append("Het nummer moet een positief geheel getal zijn.")
        nummer = None
    else:
        nummer = int(nummer_tekst)
        if nummer == instellingen.blanco_code():
            fouten.append(f"Nummer {nummer} is de blanco-code (geen dienst) en kan geen dienstcode zijn.")
        bestaand = Dienstcode.query.filter_by(nummer=nummer).first()
        if bestaand and (code is None or bestaand.id != code.id):
            fouten.append(f"Code {nummer} bestaat al.")

    omschrijving = formulier.get("omschrijving", "").strip()
    if not omschrijving:
        fouten.append("Vul een omschrijving in.")
    elif fout := lengte_fout(omschrijving, MAX_OMSCHRIJVING, "Omschrijving"):
        fouten.append(fout)

    try:
        begin = normaliseer_tijd(formulier.get("std_begin"))
        eind = normaliseer_tijd(formulier.get("std_eind"))
    except OngeldigeTijd as fout:
        fouten.append(str(fout))
        begin = eind = None
    if (begin is None) != (eind is None):
        fouten.append("Vul zowel een begin- als eindtijd in, of geen van beide.")
    elif begin is not None and begin == eind:
        fouten.append(BEGIN_IS_EIND)

    waarden = {
        "nummer": nummer,
        "omschrijving": omschrijving,
        "std_begin": begin,
        "std_eind": eind,
        "std_uren": getal(formulier.get("std_uren")),
        "kleur_achtergrond": kleur(formulier.get("kleur_achtergrond"), "#FFFFFF"),
        "kleur_tekst": kleur(formulier.get("kleur_tekst"), "#000000"),
        "vet": vinkje(formulier, "vet"),
        "cursief": vinkje(formulier, "cursief"),
        "in_agenda": vinkje(formulier, "in_agenda"),
        "hele_dag_zonder_tijden": vinkje(formulier, "hele_dag_zonder_tijden"),
        "actief": vinkje(formulier, "actief"),
    }
    return waarden, fouten


@bp.route("/dienstcodes/nieuw", methods=["GET", "POST"])
@beheerder_vereist
def dienstcode_nieuw():
    if request.method == "POST":
        waarden, fouten = _lees_formulier(None)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/dienstcode_form.html", c=None, w=waarden), 400
        code = Dienstcode(**waarden)
        db.session.add(code)
        logboek.log("Dienstcode toegevoegd", code.omschrijving, veld="nummer", nieuw=code.nummer)
        db.session.commit()
        flash(f"Dienstcode {code.nummer} toegevoegd.", "succes")
        return redirect(url_for("beheer.dienstcodes"))
    standaard = {"kleur_achtergrond": "#FFFFFF", "kleur_tekst": "#000000", "vet": True,
                 "in_agenda": True, "actief": True}
    return render_template("beheer/dienstcode_form.html", c=None, w=standaard)


@bp.route("/dienstcodes/<int:cid>", methods=["GET", "POST"])
@beheerder_vereist
def dienstcode_bewerk(cid: int):
    code = db.get_or_404(Dienstcode, cid)
    if request.method == "POST":
        waarden, fouten = _lees_formulier(code)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return render_template("beheer/dienstcode_form.html", c=code, w=waarden), 400
        # Naam of agenda-instellingen gewijzigd: toekomstige afspraken bijwerken
        agenda_velden = ("nummer", "omschrijving", "in_agenda", "hele_dag_zonder_tijden")
        agenda_geraakt = any(getattr(code, v) != waarden[v] for v in agenda_velden)
        oude_naam = code.omschrijving
        # Standaardtijden gelden alleen voor NIEUWE invoer; bestaande diensten blijven gelijk
        for veld in VELDEN:
            oud = getattr(code, veld)
            if oud != waarden[veld]:
                logboek.log("Dienstcode gewijzigd", f"Code {code.nummer}", veld=veld,
                            oud=oud, nieuw=waarden[veld])
                setattr(code, veld, waarden[veld])
        if oude_naam != code.omschrijving:
            _hernoem_aanvullingen(code, oude_naam)
        db.session.commit()
        if agenda_geraakt:
            sync_planning.plan_code(code)
        flash("Dienstcode opgeslagen. Bestaande diensten zijn niet aangepast.", "succes")
        return redirect(url_for("beheer.dienstcodes"))
    waarden = {veld: getattr(code, veld) for veld in VELDEN}
    return render_template("beheer/dienstcode_form.html", c=code, w=waarden)


def _hernoem_aanvullingen(code: Dienstcode, oude_naam: str) -> None:
    """Na hernoemen: 'VW Vroeg tot 12:00' wordt 'VW Ochtend tot 12:00' (de aanvulling blijft).

    Zonder dit zou de oude naam blijven staan, en vervalt de code bij de volgende bewerking
    van de dienstnaam (de tekst begint dan niet meer met de naam van de code).
    """
    from ...services.weekrooster import begint_met_dienstnaam

    met_aanvulling = Dienst.query.filter(Dienst.dienstcode_id == code.id, Dienst.dienstnaam_override != "")
    for dienst in met_aanvulling.all():
        if begint_met_dienstnaam(dienst.dienstnaam_override, oude_naam):
            oud = dienst.dienstnaam_override
            dienst.dienstnaam_override = (code.omschrijving + oud[len(oude_naam):])[:MAX_OMSCHRIJVING]
            dienst.versie += 1
            logboek.log("Rooster gewijzigd", f"Dienstcode {code.nummer} hernoemd", datum=dienst.datum,
                        medewerker=dienst.medewerker.naam, veld="dienstnaam", oud=oud,
                        nieuw=dienst.dienstnaam_override)


@bp.route("/dienstcodes/<int:cid>/verwijder", methods=["POST"])
@beheerder_vereist
def dienstcode_verwijder(cid: int):
    """Een code die in gebruik is kan niet weg, alleen gedeactiveerd worden."""
    code = db.get_or_404(Dienstcode, cid)
    if Dienst.query.filter_by(dienstcode_id=cid).count():
        code.actief = False
        logboek.log("Dienstcode gedeactiveerd", f"Code {code.nummer} is in gebruik",
                    veld="actief", oud=True, nieuw=False)
        flash(f"Code {code.nummer} is in gebruik en is daarom gedeactiveerd in plaats van verwijderd.",
              "info")
    else:
        logboek.log("Dienstcode verwijderd", code.omschrijving, oud=code.nummer)
        db.session.delete(code)
        flash(f"Code {code.nummer} is verwijderd.", "succes")
    db.session.commit()
    return redirect(url_for("beheer.dienstcodes"))


@bp.route("/dienstcodes/<int:cid>/standaardtijden", methods=["GET", "POST"])
@beheerder_vereist
def dienstcode_std_toepassen(cid: int):
    """Standaardtijden toepassen op alle toekomstige diensten met deze code (met voorbeeld)."""
    code = db.get_or_404(Dienstcode, cid)
    vanaf = klok.vandaag()
    if request.method == "POST":
        gewijzigd = pas_std_tijden_toe(code, vanaf)
        logboek.log("Standaardtijden toegepast",
                    f"Code {code.nummer}: {len(gewijzigd)} diensten vanaf {vanaf:%d-%m-%Y}",
                    nieuw=f"{code.std_begin or ''}-{code.std_eind or ''}")
        db.session.commit()
        sync_planning.plan_diensten(gewijzigd)  # agenda bijwerken
        flash(f"{len(gewijzigd)} diensten bijgewerkt.", "succes")
        return redirect(url_for("beheer.dienstcodes"))
    afwijkend = diensten_met_afwijkende_std_tijden(code, vanaf)
    return render_template("beheer/dienstcode_std.html", c=code, afwijkend=afwijkend, vanaf=vanaf)


@bp.route("/dienstcodes/voorbeeldpakket", methods=["POST"])
@beheerder_vereist
def voorbeeldpakket():
    codes, regels = laad_voorbeeldpakket()
    logboek.log("Dienstcodes", f"Voorbeeldpakket geladen: {codes} codes, {regels} kleurregels")
    db.session.commit()
    flash(f"{codes} dienstcodes en {regels} kleurregels toegevoegd (bestaande blijven staan).",
          "succes")
    return redirect(url_for("beheer.dienstcodes"))


# ---------- Opmerking-kleurregels ----------

@bp.route("/kleurregels/nieuw", methods=["POST"])
@beheerder_vereist
def kleurregel_nieuw():
    tekst = request.form.get("tekst", "").strip()
    bestaande = {r.tekst.casefold() for r in OpmerkingKleurregel.query.all()}
    if not tekst:
        flash("Vul een tekst in.", "fout")
    elif len(tekst) > MAX_KLEURREGEL:
        flash(f"De tekst mag hooguit {MAX_KLEURREGEL} tekens lang zijn.", "fout")
    elif tekst.casefold() in bestaande:  # de regels werken hoofdletterongevoelig
        flash(f"Er is al een kleurregel voor '{tekst}'.", "fout")
    else:
        regel = OpmerkingKleurregel(
            tekst=tekst,
            kleur_achtergrond=kleur(request.form.get("kleur_achtergrond"), "#FFFFFF"),
            kleur_achtergrond2=(kleur(request.form.get("kleur_achtergrond2"), "")
                                if vinkje(request.form, "verloop") else None) or None,
            kleur_tekst=kleur(request.form.get("kleur_tekst"), "#000000"),
        )
        db.session.add(regel)
        logboek.log("Kleurregel toegevoegd", tekst, nieuw=regel.kleur_achtergrond)
        db.session.commit()
        flash(f"Kleurregel '{tekst}' toegevoegd.", "succes")
    return redirect(url_for("beheer.dienstcodes") + "#kleurregels")


@bp.route("/kleurregels/<int:rid>/verwijder", methods=["POST"])
@beheerder_vereist
def kleurregel_verwijder(rid: int):
    regel = db.get_or_404(OpmerkingKleurregel, rid)
    logboek.log("Kleurregel verwijderd", regel.tekst)
    db.session.delete(regel)
    db.session.commit()
    flash("Kleurregel verwijderd.", "succes")
    return redirect(url_for("beheer.dienstcodes") + "#kleurregels")
