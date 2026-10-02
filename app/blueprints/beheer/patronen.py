"""Beheer → Roosterpatronen: patronen maken/wijzigen/verwijderen, een week van een patroon naar
andere weken kopiëren, een sjabloon uit het rooster, uitrollen met een droogloop en een blok weken
uit het rooster herhalen (zie services/patronen.py).

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
from ...services.patronen import HerhaalKeuzes, PatroonFout, UitrolKeuzes
from ...services.tijden import parse_datum
from ...services.weekrooster import VersieConflict
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
    if request.form.get("actie") == "kopieer":  # een week naar andere weken kopiëren, nog niet opslaan
        bron = request.form.get("kopieer_van", "")
        naar = [int(w) for w in request.form.getlist("kopieer_naar") if w.isdigit() and len(w) <= 3]
        try:
            cellen = patronen.kopieer_week(cellen, int(bron) if bron.isdigit() and len(bron) <= 3 else 0,
                                           naar, weken)
        except PatroonFout as uitzondering:
            flash(str(uitzondering), "fout")
            return _formulier(patroon, naam, weken, cellen, 400)
        flash(f"Week {bron} gekopieerd naar week {', '.join(map(str, sorted(set(naar) - {int(bron)})))}. "
              "Controleer het patroon en sla het op.", "info")
        return _formulier(patroon, naam, weken, cellen)
    # Cellen van weken die er niet (meer) zijn, tellen niet mee
    opgeslagen, fouten = patronen.sla_op(patroon, naam, gevraagd,
                                         {k: v for k, v in cellen.items() if k[0] <= weken})
    if fouten:
        for melding in fouten:
            flash(melding, "fout")
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
        except PatroonFout as uitzondering:
            fout = str(uitzondering)
    if fout:
        flash(fout, "fout")
        return redirect(url_for("beheer.patronen_lijst"))
    naam = (request.form.get("naam") or "").strip() or \
        f"{medewerker.initialen} W{van.isocalendar()[1]}-W{tot.isocalendar()[1]} {van.isocalendar()[0]}"
    flash(f"Sjabloon uit het rooster van {medewerker.naam}: controleer het patroon en sla het op.", "info")
    return _formulier(None, naam, weken, cellen, waarschuwingen=waarschuwingen)


# ---------------------------------------------------------------------------
# Gedeeld door uitrollen en herhalen: formulier, voorbeeld in de sessie en toepassen
# ---------------------------------------------------------------------------

def _gekozen_ids(fouten: list[str]) -> list[int]:
    """De aangevinkte medewerkers (veld 'mw'); onzin geeft een foutmelding."""
    gekozen = []
    for tekst in request.form.getlist("mw"):
        if not tekst.isdigit() or len(tekst) > 9:
            fouten.append("Onbekende medewerker.")
            continue
        gekozen.append(int(tekst))
    return gekozen


def _einddatum(fouten: list[str]) -> date | None:
    """De einddatum: 'of t/m datum' gaat voor 't/m week' (de zondag van die week)."""
    formulier = request.form
    tot = parse_datum(formulier.get("tot_datum", "")) if formulier.get("tot_datum", "").strip() else None
    if tot is None:
        eindweek = _maandag(formulier.get("tot_week"))
        tot = eindweek + timedelta(days=6) if eindweek else None
    if tot is None:
        fouten.append("Kies een eindweek of een einddatum.")
    return tot


def _onthoud(sleutel: str, keuzes, afdruk) -> None:
    """Bewaar de keuzes en de vingerafdruk van de inhoud (patroon of bronweken) van het voorbeeld."""
    session[sleutel] = keuzes.als_dict()
    session[f"{sleutel}_afdruk"] = afdruk()


def _voorbeeld(sleutel: str, keuzes, fouten: list[str], bereken, afdruk):
    """Het voorbeeld (droogloop) bij de bewaarde keuzes, of None als die niet (meer) kloppen.

    Getoonde keuzes en inhoud blijven in de sessie: alleen daarmee mag 'Definitief toepassen'.
    """
    if keuzes is None or fouten:
        session.pop(sleutel, None)
        session.pop(f"{sleutel}_afdruk", None)
        return None
    _onthoud(sleutel, keuzes, afdruk)  # dit voorbeeld wordt getoond
    return bereken()


def _toepassen(sleutel: str, terug: str, keuzes, fouten: list[str], afdruk, pas_toe, wat: str,
               logtekst: str):
    """'Voorbeeld bijwerken' of 'Definitief toepassen'. Geeft (resultaat, None) of (None, redirect).

    Toepassen alleen met precies de keuzes van het getoonde voorbeeld en met de bevestiging.
    pas_toe(afdruk) controleert alles opnieuw, ook of de inhoud (patroon of bronweken) nog gelijk
    is aan die van het voorbeeld. Nooit een kale foutpagina.
    """
    if fouten:
        for melding in fouten:
            flash(melding, "fout")
        return None, redirect(terug)
    getoond = session.get(sleutel)
    getoonde_afdruk = session.get(f"{sleutel}_afdruk", "")
    if request.form.get("actie") != "toepassen":
        _onthoud(sleutel, keuzes, afdruk)
        return None, redirect(terug)  # alleen het voorbeeld bijwerken
    session[sleutel] = keuzes.als_dict()
    if getoond != keuzes.als_dict():
        flash("Je keuzes zijn gewijzigd sinds het voorbeeld. Controleer het bijgewerkte voorbeeld "
              "hieronder en bevestig opnieuw.", "fout")
        return None, redirect(terug)
    if not vinkje(request.form, "bevestig"):
        flash("Vink eerst de bevestiging aan.", "fout")
        return None, redirect(terug)
    try:
        resultaat = pas_toe(getoonde_afdruk)
    except (PatroonFout, VersieConflict) as uitzondering:  # VersieConflict: een planner was tegelijk bezig
        flash(str(uitzondering), "fout")
        return None, redirect(terug)
    except Exception as uitzondering:  # nooit een kale foutpagina
        log.exception(logtekst)
        flash(f"Het {wat} is mislukt; er is niets gewijzigd ({type(uitzondering).__name__}).", "fout")
        return None, redirect(terug)
    session.pop(sleutel, None)
    session.pop(f"{sleutel}_afdruk", None)
    return resultaat, None


def _naar_week(dag: date):
    jaar, week, _ = dag.isocalendar()
    return redirect(url_for("rooster.week_tonen", jaar=jaar, week=week))


def _aantallen(resultaat: dict[str, int]) -> str:
    return ", ".join(f"{v} {k}" for k, v in resultaat.items()) + ". Er is vooraf een back-up gemaakt."


# ---------------------------------------------------------------------------
# Uitrollen: voorbeeld (droogloop) en toepassen
# ---------------------------------------------------------------------------

def _keuzes_uit_formulier(patroon: RoosterPatroon) -> tuple[UitrolKeuzes | None, list[str]]:
    fouten = []
    gekozen = []
    for mid in _gekozen_ids(fouten):
        start = request.form.get(f"start-{mid}", "1").strip()
        gekozen.append((mid, int(start) if start.isdigit() and len(start) <= 3 else 0))
    van = _maandag(request.form.get("van"))
    if van is None:
        fouten.append("Kies een geldige startweek.")
    tot = _einddatum(fouten)
    if fouten:
        return None, fouten
    keuzes = UitrolKeuzes(patroon.id, tuple(gekozen), van, tot, request.form.get("modus", ""),
                          request.form.get("feestdagen", ""))
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
        resultaat, antwoord = _toepassen(
            "patroon_keuzes", url_for("beheer.patroon_uitrollen", pid=pid), keuzes, fouten,
            lambda: patronen.vingerafdruk(patroon), lambda afdruk: patronen.pas_toe(patroon, keuzes, afdruk),
            "toepassen", "Roosterpatroon toepassen mislukt")
        if antwoord is not None:
            return antwoord
        flash(f"Patroon '{patroon.naam}' toegepast: " + _aantallen(resultaat), "succes")
        return _naar_week(keuzes.van)

    keuzes = _keuzes_uit_sessie(patroon)
    effect = _voorbeeld("patroon_keuzes", keuzes, keuzes.controleer(patroon) if keuzes else [],
                        lambda: patronen.effect(patroon, keuzes), lambda: patronen.vingerafdruk(patroon))
    huidig = klok.vandaag() - timedelta(days=klok.vandaag().weekday())
    starts = dict(keuzes.medewerkers) if keuzes else {}
    return render_template(
        "beheer/patroon_uitrollen.html", patroon=patroon, cellen=patroon.cellen(), dagen=DAGEN_KORT,
        medewerkers=_medewerkers(), keuzes=keuzes, effect=effect, starts=starts, modi=patronen.MODI,
        feestdag_keuzes=patronen.FEESTDAG_KEUZES,
        van=_weektekst(keuzes.van if keuzes else huidig),
        tot_datum=keuzes.tot.isoformat() if keuzes else "",
        tot_week=_weektekst(huidig + timedelta(weeks=patroon.weken - 1)))


# ---------------------------------------------------------------------------
# Rooster herhalen: een blok weken (bijv. een 8-wekelijks rooster) herhalen
# ---------------------------------------------------------------------------

def _herhaal_uit_formulier() -> tuple[HerhaalKeuzes | None, list[str]]:
    fouten = []
    gekozen = _gekozen_ids(fouten)
    bron, van = _maandag(request.form.get("bron")), _maandag(request.form.get("van"))
    if bron is None:
        fouten.append("Kies een geldige eerste bronweek.")
    if van is None:
        fouten.append("Kies een geldige startweek.")
    weken = patronen.lees_weken(request.form.get("weken", ""))
    if weken is None:
        fouten.append(f"Herhaal 1 t/m {patronen.MAX_WEKEN} weken.")
    tot = _einddatum(fouten)
    if fouten:
        return None, fouten
    keuzes = HerhaalKeuzes(tuple(gekozen), bron, weken, van, tot, request.form.get("modus", ""),
                           request.form.get("feestdagen", ""),
                           request.form.get("soort", patronen.KOPIE_CODES))
    return keuzes, keuzes.controleer()


def _herhaal_uit_sessie() -> HerhaalKeuzes | None:
    bewaard = session.get("herhaal_keuzes")
    return HerhaalKeuzes.uit_dict(bewaard) if bewaard else None


@bp.route("/patronen/herhalen", methods=["GET", "POST"])
@beheerder_vereist
def rooster_herhalen():
    """Plan een blok weken in het weekrooster en herhaal het voor het hele team (met droogloop)."""
    if request.method == "POST":
        keuzes, fouten = _herhaal_uit_formulier()
        resultaat, antwoord = _toepassen(
            "herhaal_keuzes", url_for("beheer.rooster_herhalen"), keuzes, fouten,
            lambda: patronen.herhaal_vingerafdruk(keuzes),
            lambda afdruk: patronen.herhaal_pas_toe(keuzes, afdruk), "herhalen", "Rooster herhalen mislukt")
        if antwoord is not None:
            return antwoord
        flash("Rooster herhaald: " + _aantallen(resultaat), "succes")
        return _naar_week(keuzes.van)

    keuzes = _herhaal_uit_sessie()
    effect = _voorbeeld("herhaal_keuzes", keuzes, keuzes.controleer() if keuzes else [],
                        lambda: patronen.herhaal_effect(keuzes),
                        lambda: patronen.herhaal_vingerafdruk(keuzes))
    if effect is None:
        keuzes = None
    huidig = klok.vandaag() - timedelta(days=klok.vandaag().weekday())
    weken = keuzes.weken if keuzes else patronen.STANDAARD_WEKEN
    bron = keuzes.bron if keuzes else huidig
    van = keuzes.van if keuzes else bron + timedelta(weeks=weken)
    medewerkers = _medewerkers()
    if keuzes:
        gekozen = set(keuzes.medewerkers)
    else:  # standaard: wie er dan nog is én diensten in de bronweken heeft (anders wordt alles gewist)
        met_rooster = patronen.met_diensten(bron, bron + timedelta(weeks=weken, days=-1))
        gekozen = {m.id for m in medewerkers if m.is_zichtbaar_op(van) and m.id in met_rooster}
    return render_template(
        "beheer/rooster_herhalen.html", keuzes=keuzes, effect=effect, medewerkers=medewerkers,
        gekozen=gekozen, modi=patronen.MODI, feestdag_keuzes=patronen.FEESTDAG_KEUZES,
        kopie_soorten=patronen.KOPIE_SOORTEN, weken=weken,
        max_weken=patronen.MAX_WEKEN, bron=_weektekst(bron), van=_weektekst(van),
        tot_datum=keuzes.tot.isoformat() if keuzes else "",
        tot_week=_weektekst(van + timedelta(weeks=2 * weken - 1)))
