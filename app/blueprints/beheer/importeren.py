"""Beheer → Excel import/export: importeren uit het oude Excel-bestand (.xlsm) of een eigen
Excel-export (.xlsx). Het exporteren zelf staat in exporteren.py (formulier onderaan dit scherm).

Stap 1: bestand uploaden.
Stap 2: 'Rooster voor jaar' kiezen (verplicht; voorstel uit Kalender!E2 of de bestandsnaam).
Stap 3: droogloop met voorbeeld en keuzes: overschrijfmodus (alles, gedeeltelijk of alleen
        lege dagen) en welke algemene gegevens overgenomen worden. Er wordt nog niets opgeslagen.
Stap 4: bevestigen -> definitief importeren, alleen met precies de keuzes uit het getoonde
        voorbeeld (anders eerst een nieuw voorbeeld). Het bestand wordt daarna verwijderd.
"""

import logging
import os
import secrets

from flask import flash, redirect, render_template, request, session, url_for

from ...models import Medewerker
from ...services import backup, klok
from ...services.excel_export import SOORTEN
from ...services.excel_import import (
    MODI,
    MODUS_ALLES,
    ImportFout,
    ImportKeuzes,
    controleer_bestand,
    effect,
    import_map,
    importeer,
    jaar_uit_bestand,
    jaar_uit_naam,
    lees_bestand,
)
from ...services.kalender import MAX_JAAR, MIN_JAAR, eerste_en_laatste_dag_isojaar
from ...services.tijden import is_cijfers, parse_datum
from ..hulp import beheerder_vereist, vinkje
from . import bp

TOEGESTAAN = (".xlsm", ".xlsx")
ONDERDELEN = ("contracturen", "toeslagen", "vakanties", "codes")
log = logging.getLogger(__name__)


def _opgeslagen_pad() -> str | None:
    naam = session.get("import_bestand", "")
    if not naam or "/" in naam or "\\" in naam:
        return None
    pad = os.path.join(import_map(), naam)
    return pad if os.path.exists(pad) else None


def _ruim_op() -> None:
    pad = _opgeslagen_pad()
    if pad:
        os.remove(pad)
    for sleutel in ("import_bestand", "import_naam", "import_jaar", "import_keuzes"):
        session.pop(sleutel, None)


def _export_context() -> dict:
    """Het exportformulier onderaan het scherm, met de keuzes van een vorige poging."""
    vorige = {veld: request.args.get(f"export_{veld}", "") for veld in ("soort", "jaar", "week", "van",
                                                                       "tot", "medewerker")}
    huidig = klok.vandaag().isocalendar()
    vorige["soort"] = vorige["soort"] or "week"
    vorige["jaar"] = vorige["jaar"] or huidig[0]
    vorige["week"] = vorige["week"] or huidig[1]
    return {"export": vorige, "export_soorten": SOORTEN, "min_jaar": MIN_JAAR, "max_jaar": MAX_JAAR,
            "export_medewerkers": Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()}


def _lees_jaar(tekst: str | None) -> int | None:
    tekst = (tekst or "").strip()
    if not is_cijfers(tekst) or not MIN_JAAR <= int(tekst) <= MAX_JAAR:
        return None
    return int(tekst)


@bp.route("/importeren", methods=["GET", "POST"])
@beheerder_vereist
def excel_import():
    """Stap 1 (uploaden) en stap 2 (jaar kiezen)."""
    if request.method == "POST":
        bestand = request.files.get("bestand")
        if not bestand or not bestand.filename.lower().endswith(TOEGESTAAN):
            flash("Kies een Excel-bestand (.xlsm of .xlsx).", "fout")
            return redirect(url_for("beheer.excel_import"))
        _ruim_op()
        naam = secrets.token_hex(8) + ".xlsm"
        pad = os.path.join(import_map(), naam)
        bestand.save(pad)
        os.chmod(pad, 0o600)
        session["import_bestand"] = naam
        try:
            controleer_bestand(pad)
        except ImportFout as fout:
            _ruim_op()
            flash(str(fout), "fout")
            return redirect(url_for("beheer.excel_import"))
        session["import_naam"] = os.path.basename(bestand.filename)[:120]
        jaar = _lees_jaar(request.form.get("jaar"))
        if jaar is not None:  # meteen ingevuld bij het uploaden
            session["import_jaar"] = jaar
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        return redirect(url_for("beheer.excel_import"))

    pad = _opgeslagen_pad()
    if pad is None:
        return render_template("beheer/importeren.html", stap="upload", plan=None, **_export_context())
    # Bestand ontvangen: jaar kiezen. Voorstel: Kalender!E2, anders de bestandsnaam (nooit stil 'nu')
    voorstel = (session.get("import_jaar") or jaar_uit_bestand(pad)
                or jaar_uit_naam(session.get("import_naam", "")))
    return render_template("beheer/importeren.html", stap="jaar", plan=None, voorstel=voorstel,
                           bestandsnaam=session.get("import_naam", ""), **_export_context())


@bp.route("/importeren/jaar", methods=["POST"])
@beheerder_vereist
def excel_import_jaar():
    """Stap 2: het gekozen jaar bewaren (naast het bestand in de sessie)."""
    if _opgeslagen_pad() is None:
        flash("Upload eerst een bestand.", "info")
        return redirect(url_for("beheer.excel_import"))
    jaar = _lees_jaar(request.form.get("jaar"))
    if jaar is None:
        flash(f"Vul bij 'Rooster voor jaar' een jaar in tussen {MIN_JAAR} en {MAX_JAAR}.", "fout")
        return redirect(url_for("beheer.excel_import"))
    if session.get("import_jaar") != jaar:
        session.pop("import_keuzes", None)  # ander jaar: keuzes (periode) opnieuw bepalen
    session["import_jaar"] = jaar
    return redirect(url_for("beheer.excel_import_voorbeeld"))


def _keuzes_uit_formulier(plan) -> tuple[ImportKeuzes, list[str]]:
    """De keuzes uit het droogloopformulier, plus foutmeldingen."""
    formulier = request.form
    fouten = []
    van_tekst, tot_tekst = formulier.get("van", "").strip(), formulier.get("tot", "").strip()
    van, tot = parse_datum(van_tekst), parse_datum(tot_tekst)
    if (van_tekst and van is None) or (tot_tekst and tot is None):
        fouten.append("Vul een geldige periode in (of laat die leeg voor het hele jaar).")
    keuzes = ImportKeuzes(
        modus=formulier.get("modus", MODUS_ALLES),
        medewerkers=tuple(formulier.getlist("medewerkers")),
        van=van, tot=tot,
        dagopmerkingen_bij_selectie=vinkje(formulier, "dagopmerkingen_bij_selectie"),
        **{o: formulier.get(o) == "ja" for o in ONDERDELEN},
    ).genormaliseerd()
    return keuzes, fouten + keuzes.controleer(plan)


def _keuzes_uit_sessie(plan) -> ImportKeuzes:
    bewaard = session.get("import_keuzes")
    if not bewaard:
        return ImportKeuzes.standaard(plan)
    return ImportKeuzes(
        modus=bewaard["modus"], medewerkers=tuple(bewaard["medewerkers"]),
        van=parse_datum(bewaard["van"]), tot=parse_datum(bewaard["tot"]),
        dagopmerkingen_bij_selectie=bewaard["dagopmerkingen_bij_selectie"],
        **{o: bewaard[o] for o in ONDERDELEN},
    ).genormaliseerd()


@bp.route("/importeren/voorbeeld", methods=["GET", "POST"])
@beheerder_vereist
def excel_import_voorbeeld():
    """Stap 3 en 4: droogloop met keuzes, en definitief importeren."""
    pad = _opgeslagen_pad()
    if pad is None:
        flash("Upload eerst een bestand.", "info")
        return redirect(url_for("beheer.excel_import"))
    jaar = session.get("import_jaar")
    if jaar is None:
        return redirect(url_for("beheer.excel_import"))  # eerst het jaar kiezen
    try:
        plan = lees_bestand(pad, jaar)
    except ImportFout as fout:
        _ruim_op()
        flash(str(fout), "fout")
        return redirect(url_for("beheer.excel_import"))

    if request.method == "POST":
        keuzes, fouten = _keuzes_uit_formulier(plan)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        getoond = session.get("import_keuzes")
        session["import_keuzes"] = keuzes.als_dict()
        if request.form.get("actie") != "importeren":
            return redirect(url_for("beheer.excel_import_voorbeeld"))  # alleen het voorbeeld bijwerken
        if getoond != keuzes.als_dict():
            flash("Je keuzes zijn gewijzigd sinds het voorbeeld. Controleer het bijgewerkte voorbeeld "
                  "hieronder en bevestig opnieuw.", "fout")
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        if not vinkje(request.form, "bevestig"):
            flash("Vink eerst de bevestiging aan.", "fout")
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        try:
            backup.maak_backup("voor-import")  # altijd eerst een back-up
            resultaat = importeer(plan, keuzes)  # controleert de keuzes opnieuw
        except ImportFout as fout:
            flash(str(fout), "fout")
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        except Exception as fout:  # nooit een kale foutpagina
            log.exception("Excel-import mislukt")
            flash(f"De import is mislukt; er is niets geïmporteerd ({type(fout).__name__}).", "fout")
            return redirect(url_for("beheer.excel_import_voorbeeld"))
        _ruim_op()
        flash("Import klaar: " + ", ".join(f"{v} {k}" for k, v in resultaat.items())
              + ". Er is vooraf een back-up gemaakt.", "succes")
        return redirect(url_for("kalender.jaar", jaar=plan.jaar))

    keuzes = _keuzes_uit_sessie(plan)
    if keuzes.controleer(plan):  # bijv. een ander jaar gekozen: terug naar de standaard
        keuzes = ImportKeuzes.standaard(plan)
    session["import_keuzes"] = keuzes.als_dict()  # dit voorbeeld wordt getoond
    eerste, laatste = eerste_en_laatste_dag_isojaar(plan.jaar)
    return render_template("beheer/importeren.html", stap="voorbeeld", plan=plan, keuzes=keuzes,
                           effect=effect(plan, keuzes), modi=MODI, onderdelen=ONDERDELEN,
                           eerste=eerste, laatste=laatste, bestandsnaam=session.get("import_naam", ""),
                           handmatige_uren=plan.handmatige_uren(),
                           week_verschillen=plan.weektotaal_verschillen(), **_export_context())


@bp.route("/importeren/annuleren", methods=["POST"])
@beheerder_vereist
def excel_import_annuleren():
    _ruim_op()
    flash("Import geannuleerd; het bestand is verwijderd.", "info")
    return redirect(url_for("beheer.excel_import"))
