"""Beheer → Roosterpatronen: patronen maken/wijzigen/verwijderen, een sjabloon uit het rooster,
en uitrollen met een droogloop (zie services/patronen.py).

Uitrollen gaat als de import: eerst 'Voorbeeld bijwerken' (er wordt niets opgeslagen), dan
'Definitief toepassen', alleen met precies de keuzes van het getoonde voorbeeld. Bij het
toepassen wordt alles opnieuw gecontroleerd en eerst een back-up gemaakt.
"""

import logging
import re
from datetime import date, timedelta

from flask import flash, redirect, render_template, request, session, url_for

from ...extensions import db
from ...models import Medewerker, RoosterPatroon
from ...services import klok, patronen
from ...services.kalender import aantal_weken
from ...services.patronen import PatroonFout, UitrolKeuzes
from ...services.tijden import parse_datum
from ..hulp import beheerder_vereist, vinkje
from . import bp

WEEK = re.compile(r"^(\d{4})-W(\d{1,2})$")
DAGEN_KORT = ["ma", "di", "wo", "do", "vr", "za", "zo"]
log = logging.getLogger(__name__)


def _maandag(tekst: str | None) -> date | None:
    """'2026-W10' (zoals <input type="week">) -> maandag van die week, of None."""
    gevonden = WEEK.match((tekst or "").strip())
    if not gevonden:
        return None
    jaar, week = int(gevonden.group(1)), int(gevonden.group(2))
    if not (1 <= jaar <= 9998 and 1 <= week <= aantal_weken(jaar)):
        return None
    return date.fromisocalendar(jaar, week, 1)


def _weektekst(dag: date) -> str:
    jaar, week, _ = dag.isocalendar()
    return f"{jaar}-W{week:02d}"


def _medewerkers():
    return Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()


# ---------------------------------------------------------------------------
# Overzicht, maken, wijzigen, verwijderen, sjabloon
# ---------------------------------------------------------------------------

@bp.route("/patronen")
@beheerder_vereist
def patronen_lijst():
    huidig = klok.vandaag() - timedelta(days=klok.vandaag().weekday())
    lijst = RoosterPatroon.query.order_by(RoosterPatroon.naam).all()
    return render_template("beheer/patronen.html", patronen=lijst, medewerkers=_medewerkers(),
                           van=_weektekst(huidig),
                           tot=_weektekst(huidig + timedelta(weeks=patronen.STANDAARD_WEKEN - 1)),
                           max_weken=patronen.MAX_WEKEN)


def _cellen_uit_formulier(weken: int) -> dict[tuple[int, int], str]:
    return {(w, d): request.form.get(f"c-{w}-{d}", "") for w in range(1, weken + 1) for d in range(7)}


def _formulier(patroon, naam, weken, cellen, status=200, waarschuwingen=()):
    return render_template("beheer/patroon_form.html", patroon=patroon, naam=naam, weken=weken,
                           cellen=cellen, dagen=DAGEN_KORT, max_weken=patronen.MAX_WEKEN,
                           waarschuwingen=waarschuwingen), status


@bp.route("/patronen/nieuw", methods=["GET", "POST"])
@bp.route("/patronen/<int:pid>", methods=["GET", "POST"])
@beheerder_vereist
def patroon_bewerken(pid: int | None = None):
    patroon = db.get_or_404(RoosterPatroon, pid) if pid is not None else None
    if request.method == "GET":
        if patroon is None:
            return _formulier(None, "", patronen.STANDAARD_WEKEN, {})
        return _formulier(patroon, patroon.naam, patroon.weken, patroon.cellen())
    naam = request.form.get("naam", "")
    gevraagd = request.form.get("weken", "")
    weken = patronen.lees_weken(gevraagd) or patronen.STANDAARD_WEKEN
    cellen = _cellen_uit_formulier(patronen.MAX_WEKEN)
    if request.form.get("actie") == "weken":  # alleen het aantal weken aanpassen, nog niet opslaan
        if patronen.lees_weken(gevraagd) is None:
            flash(f"Een patroon heeft 1 t/m {patronen.MAX_WEKEN} weken.", "fout")
        return _formulier(patroon, naam, weken, cellen)
    # Cellen van weken die er niet (meer) zijn, tellen niet mee
    opgeslagen, fouten = patronen.sla_op(patroon, naam, gevraagd,
                                         {k: v for k, v in cellen.items() if k[0] <= weken})
    if fouten:
        for fout in fouten:
            flash(fout, "fout")
        return _formulier(patroon, naam, weken, cellen, 400)
    flash(f"Patroon '{opgeslagen.naam}' opgeslagen.", "succes")
    return redirect(url_for("beheer.patronen_lijst"))


@bp.route("/patronen/<int:pid>/verwijderen", methods=["POST"])
@beheerder_vereist
def patroon_verwijderen(pid: int):
    patroon = db.get_or_404(RoosterPatroon, pid)
    naam = patroon.naam
    patronen.verwijder(patroon)
    flash(f"Patroon '{naam}' verwijderd. Het rooster zelf is niet veranderd.", "succes")
    return redirect(url_for("beheer.patronen_lijst"))


@bp.route("/patronen/sjabloon", methods=["POST"])
@beheerder_vereist
def patroon_sjabloon():
    """Een nieuw patroon uit het rooster (nog niet opgeslagen: eerst controleren)."""
    medewerker_id = request.form.get("medewerker", "")
    medewerker = db.session.get(Medewerker, int(medewerker_id)) \
        if medewerker_id.isdigit() and len(medewerker_id) <= 9 else None
    van, tot = _maandag(request.form.get("van")), _maandag(request.form.get("tot"))
    fout = None
    if medewerker is None:
        fout = "Kies een medewerker."
    elif van is None or tot is None:
        fout = "Kies een geldige eerste en laatste week."
    else:
        try:
            cellen, weken, waarschuwingen = patronen.sjabloon(medewerker, van, tot)
        except PatroonFout as fout_:
            fout = str(fout_)
    if fout:
        flash(fout, "fout")
        return redirect(url_for("beheer.patronen_lijst"))
    naam = (request.form.get("naam") or "").strip() or \
        f"{medewerker.initialen} W{van.isocalendar()[1]}-W{tot.isocalendar()[1]} {van.isocalendar()[0]}"
    flash(f"Sjabloon uit het rooster van {medewerker.naam}: controleer het patroon en sla het op.", "info")
    return _formulier(None, naam, weken, cellen, waarschuwingen=waarschuwingen)


# ---------------------------------------------------------------------------
# Uitrollen: voorbeeld (droogloop) en toepassen
# ---------------------------------------------------------------------------

def _keuzes_uit_formulier(patroon: RoosterPatroon) -> tuple[UitrolKeuzes | None, list[str]]:
    formulier = request.form
    fouten = []
    gekozen = []
    for tekst in formulier.getlist("mw"):
        if not tekst.isdigit() or len(tekst) > 9:
            fouten.append("Onbekende medewerker.")
            continue
        start = formulier.get(f"start-{tekst}", "1").strip()
        gekozen.append((int(tekst), int(start) if start.isdigit() and len(start) <= 3 else 0))
    van = _maandag(formulier.get("van"))
    if van is None:
        fouten.append("Kies een geldige startweek.")
    tot = parse_datum(formulier.get("tot_datum", "")) if formulier.get("tot_datum", "").strip() else None
    if tot is None:
        eindweek = _maandag(formulier.get("tot_week"))
        tot = eindweek + timedelta(days=6) if eindweek else None
    if tot is None:
        fouten.append("Kies een eindweek of een einddatum.")
    if fouten:
        return None, fouten
    keuzes = UitrolKeuzes(patroon.id, tuple(gekozen), van, tot, formulier.get("modus", ""),
                          formulier.get("feestdagen", ""))
    return keuzes, keuzes.controleer(patroon)


def _keuzes_uit_sessie(patroon: RoosterPatroon) -> UitrolKeuzes | None:
    bewaard = session.get("patroon_keuzes")
    if not bewaard or bewaard.get("patroon_id") != patroon.id:
        return None
    return UitrolKeuzes(patroon.id, tuple(tuple(m) for m in bewaard["medewerkers"]),
                        date.fromisoformat(bewaard["van"]), date.fromisoformat(bewaard["tot"]),
                        bewaard["modus"], bewaard["feestdagen"])


@bp.route("/patronen/<int:pid>/uitrollen", methods=["GET", "POST"])
@beheerder_vereist
def patroon_uitrollen(pid: int):
    patroon = db.get_or_404(RoosterPatroon, pid)
    if request.method == "POST":
        keuzes, fouten = _keuzes_uit_formulier(patroon)
        if fouten:
            for fout in fouten:
                flash(fout, "fout")
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))
        getoond = session.get("patroon_keuzes")
        session["patroon_keuzes"] = keuzes.als_dict()
        if request.form.get("actie") != "toepassen":
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))  # alleen het voorbeeld bijwerken
        if getoond != keuzes.als_dict():
            flash("Je keuzes zijn gewijzigd sinds het voorbeeld. Controleer het bijgewerkte voorbeeld "
                  "hieronder en bevestig opnieuw.", "fout")
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))
        if not vinkje(request.form, "bevestig"):
            flash("Vink eerst de bevestiging aan.", "fout")
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))
        try:
            resultaat = patronen.pas_toe(patroon, keuzes)  # controleert de keuzes opnieuw
        except PatroonFout as fout:
            flash(str(fout), "fout")
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))
        except Exception as fout:  # nooit een kale foutpagina
            log.exception("Roosterpatroon toepassen mislukt")
            flash(f"Het toepassen is mislukt; er is niets gewijzigd ({type(fout).__name__}).", "fout")
            return redirect(url_for("beheer.patroon_uitrollen", pid=pid))
        session.pop("patroon_keuzes", None)
        flash(f"Patroon '{patroon.naam}' toegepast: " + ", ".join(f"{v} {k}" for k, v in resultaat.items())
              + ". Er is vooraf een back-up gemaakt.", "succes")
        jaar, week, _ = keuzes.van.isocalendar()
        return redirect(url_for("rooster.week_tonen", jaar=jaar, week=week))

    keuzes = _keuzes_uit_sessie(patroon)
    effect = None
    if keuzes is not None and not keuzes.controleer(patroon):
        effect = patronen.effect(patroon, keuzes)
        session["patroon_keuzes"] = keuzes.als_dict()  # dit voorbeeld wordt getoond
    else:
        session.pop("patroon_keuzes", None)
    huidig = klok.vandaag() - timedelta(days=klok.vandaag().weekday())
    starts = dict(keuzes.medewerkers) if keuzes else {}
    return render_template(
        "beheer/patroon_uitrollen.html", patroon=patroon, cellen=patroon.cellen(), dagen=DAGEN_KORT,
        medewerkers=_medewerkers(), keuzes=keuzes, effect=effect, starts=starts, modi=patronen.MODI,
        feestdag_keuzes=patronen.FEESTDAG_KEUZES,
        van=_weektekst(keuzes.van if keuzes else huidig),
        tot_datum=keuzes.tot.isoformat() if keuzes else "",
        tot_week=_weektekst(huidig + timedelta(weeks=patroon.weken - 1)))
