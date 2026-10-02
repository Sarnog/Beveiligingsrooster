"""Roosterlogica: uren van diensten berekenen en bijwerken."""

from datetime import date

from ..extensions import db
from ..models import Dienst, Dienstcode
from . import instellingen, klok
from .feestdagen import feestdagen_in_periode
from .tijden import tijd_naar_minuten
from .urenberekening import (
    bereken_uren,
    dagfactor,
    gewerkte_minuten,
    pauze_aftrek,
    uren_exact,
    uren_uit_minuten,
)

_ZOEKEN = object()  # uren_voor: de andere dienst van de dag zelf opzoeken


class UrenContext:
    """Alles wat nodig is om uren te berekenen, één keer opgehaald.

    Zo hoeven we bij het herberekenen van duizenden diensten niet steeds
    opnieuw instellingen en feestdagen uit de database te lezen.
    """

    def __init__(self, van: date, tot: date) -> None:
        self.toeslagen = instellingen.toeslagen()
        self.opmerkingtijden_meetellen = instellingen.lees_bool("opmerkingtijden_meetellen")
        self.pauze = instellingen.pauze()
        self.feestdagen = set(feestdagen_in_periode(van, tot).keys())

    def factor(self, datum: date) -> float:
        return dagfactor(
            datum,
            self.toeslagen["factor_zaterdag"],
            self.toeslagen["factor_zondag"],
            is_feestdag=datum in self.feestdagen,
            factor_feestdag=self.toeslagen["factor_feestdag"],
        )


def tijden_overlappen(begin1: str | None, eind1: str | None,
                      begin2: str | None, eind2: str | None) -> bool:
    """True als twee tijdvakken op dezelfde dag elkaar overlappen.

    Eind vóór begin = het vak loopt door tot na middernacht. Zonder begin of eind: geen overlap.
    """
    vakken = []
    for begin, eind in ((begin1, eind1), (begin2, eind2)):
        b, e = tijd_naar_minuten(begin), tijd_naar_minuten(eind)
        if b is None or e is None:
            return False
        vakken.append((b, e + 1440 if e < b else e))
    (b1, e1), (b2, e2) = vakken
    return b1 < e2 and b2 < e1


def opmerking_valt_samen(dienst, tweede: Dienst | None) -> bool:
    """De opmerkingtijden van dienst 1 vallen (deels) samen met een dienst van die dag.

    Met dienst 1 zelf of met dienst 2: die tijd telt al bij die dienst en mag niet nog eens
    meetellen. Zo stond een tweede dienst vóór versie 1.4.0 (en in het oude Excel) in het
    rooster: als opmerking met tijden, bijv. 'Soc. Veiligh. OB 13:00-17:00'. Wordt dat daarna
    een echte dienst (dienst 2, of dienst 1 zelf, bijv. 'Cursus 13:00-17:00'), dan telt dat
    tijdvak alleen nog bij die dienst. Opmerkingtijden op een ander moment tellen gewoon mee.
    """
    if tijden_overlappen(dienst.opmerking_begin, dienst.opmerking_eind, dienst.begin, dienst.eind):
        return True
    return tweede is not None and tijden_overlappen(
        dienst.opmerking_begin, dienst.opmerking_eind, tweede.begin, tweede.eind)


def _andere_dienst_van(dienst) -> Dienst | None:
    """De andere dienst van dezelfde dag (alleen voor een opgeslagen dienst)."""
    volgnummer = getattr(dienst, "volgnummer", None)
    if volgnummer not in (1, 2) or not getattr(dienst, "medewerker_id", None):
        return None
    with db.session.no_autoflush:
        return Dienst.query.filter_by(medewerker_id=dienst.medewerker_id, datum=dienst.datum,
                                      volgnummer=3 - volgnummer).first()


def dag_uren(dienst1, dienst2, context: UrenContext) -> tuple[float | None, float | None]:
    """Uren van dienst 1 en dienst 2 van één dag (dienst1 of dienst2 mag None zijn).

    Delen van de dag: de tijden van dienst 1, de opmerkingtijden van dienst 1 (als die
    meetellen en niet samenvallen met een dienst, zie opmerking_valt_samen) en de tijden van
    dienst 2. De pauze geldt per dag: de staffel op het totaal van alle delen, één keer
    afgetrokken bij het langste deel (bij gelijke lengte het eerste). Elk deel krijgt de
    toeslagfactor en wordt exact op kwartieren afgerond (uren_exact, zoals de Excel-export).
    Eén deel: precies de oude VBA (uren_uit_minuten), ook met zijn kommagetallen.
    Zelf ingevulde uren gaan voor en tellen niet mee in het totaal voor de pauze.
    """
    if dienst2 is not None and dienst2.is_leeg:
        dienst2 = None
    if dienst1 is None and dienst2 is None:
        return None, None
    datum = (dienst1 or dienst2).datum
    delen = []  # (volgnummer, begin, eind) in minuten
    if dienst1 is not None and dienst1.uren_handmatig is None:
        tijden = [(dienst1.begin, dienst1.eind)]
        if context.opmerkingtijden_meetellen and not opmerking_valt_samen(dienst1, dienst2):
            tijden.append((dienst1.opmerking_begin, dienst1.opmerking_eind))
        delen += [(1, tijd_naar_minuten(b), tijd_naar_minuten(e)) for b, e in tijden]
    if dienst2 is not None and dienst2.uren_handmatig is None:
        delen.append((2, tijd_naar_minuten(dienst2.begin), tijd_naar_minuten(dienst2.eind)))
    delen = [d for d in delen if d[1] is not None and d[2] is not None]
    factor = context.factor(datum)
    uren: dict[int, float | None] = {1: None, 2: None}
    if len(delen) == 1:  # één deel: de pauze uit de staffel, precies als de VBA
        volgnummer, begin, eind = delen[0]
        uren[volgnummer] = uren_uit_minuten(begin, eind, factor, context.pauze)
    elif delen:
        minuten = [gewerkte_minuten(begin, eind) for _, begin, eind in delen]
        aftrek = pauze_aftrek(sum(minuten) / 60, context.pauze)
        langste = minuten.index(max(minuten))
        for nummer, (volgnummer, _, _) in enumerate(delen):
            deel = uren_exact(minuten[nummer], factor, aftrek if nummer == langste else 0)
            uren[volgnummer] = (uren[volgnummer] or 0) + deel
    if dienst1 is not None and dienst1.uren_handmatig is not None:
        uren[1] = dienst1.uren_handmatig
    if dienst2 is not None and dienst2.uren_handmatig is not None:
        uren[2] = dienst2.uren_handmatig
    return uren[1], uren[2]


def uren_voor(dienst: Dienst, context: UrenContext, ander=_ZOEKEN) -> float | None:
    """Uren van één dienst: de tijdenregel, plus eventueel de opmerkingtijden (zie dag_uren).

    De pauze geldt per dag, dus de andere dienst van die dag telt mee. ander: die andere
    dienst als die al bekend is (scheelt een query; None = er is geen andere dienst).

    Zelf ingevulde uren (uren_handmatig) gaan altijd voor, zonder toeslagfactor:
    zo werkte het ook in Excel als je een getal in de urenkolom typte.
    """
    if dienst.uren_handmatig is not None:
        return dienst.uren_handmatig
    if ander is _ZOEKEN:
        ander = _andere_dienst_van(dienst)
    if getattr(dienst, "volgnummer", 1) == 2:
        return dag_uren(ander, dienst, context)[1]
    return dag_uren(dienst, ander, context)[0]


def herbereken_alle(van: date | None = None, tot: date | None = None) -> int:
    """Herbereken de uren van alle diensten (optioneel binnen een periode).

    Nodig na het wijzigen van toeslagfactoren, de pauzeaftrek of feestdagen. Geeft het aantal
    diensten terug waarvan de uren veranderd zijn.
    """
    query = Dienst.query
    if van:
        query = query.filter(Dienst.datum >= van)
    if tot:
        query = query.filter(Dienst.datum <= tot)
    diensten = query.all()
    if not diensten:
        return 0
    eerste = min(d.datum for d in diensten)
    laatste = max(d.datum for d in diensten)
    context = UrenContext(eerste, laatste)
    per_dag = {(d.medewerker_id, d.datum, d.volgnummer): d for d in diensten}
    gewijzigd = 0
    for dienst in diensten:
        nieuw = uren_voor(dienst, context, per_dag.get((dienst.medewerker_id, dienst.datum,
                                                         3 - dienst.volgnummer)))
        if nieuw != dienst.uren_berekend:
            dienst.uren_berekend = nieuw
            gewijzigd += 1
    db.session.commit()
    return gewijzigd


def _is_dagtotaal(dienst1: Dienst, dienst2: Dienst, context: UrenContext) -> bool:
    """Zijn de zelf ingevulde uren van dienst 1 het totaal van de hele dag?

    Zo kwam het uit de import (dienst plus een training op de opmerkingregel, zoals in Excel)
    of van vóór versie 1.6.0: dienst 1 + dienst 2, of dienst 1 + de opmerkingtijden die
    samenvallen met een dienst; met de pauze per dienst (zoals Excel) of per dag. Andere
    eigen uren laten we staan (die zijn bewust zo gezet).
    """
    from types import SimpleNamespace

    factor = context.factor(dienst1.datum)
    eigen = bereken_uren(dienst1.begin, dienst1.eind, factor, context.pauze) or 0
    totalen = [eigen + (bereken_uren(dienst2.begin, dienst2.eind, factor, context.pauze) or 0)]
    if opmerking_valt_samen(dienst1, dienst2):
        totalen.append(eigen + (bereken_uren(dienst1.opmerking_begin, dienst1.opmerking_eind, factor,
                                             context.pauze) or 0))
    zonder = SimpleNamespace(datum=dienst1.datum, begin=dienst1.begin, eind=dienst1.eind, uren_handmatig=None,
                             opmerking_begin=dienst1.opmerking_begin, opmerking_eind=dienst1.opmerking_eind)
    totalen.append(sum(u or 0 for u in dag_uren(zonder, dienst2, context)))
    return any(abs(dienst1.uren_handmatig - totaal) < 0.01 for totaal in totalen)


def herstel_dubbele_uren() -> int:
    """Kijk alle dagen na en corrigeer de uren volgens de huidige regels (eenmalig, zie worker).

    Raakt alleen dagen met twee delen: twee diensten, of een dienst met opmerkingtijden.
    - Opmerkingtijden die samenvallen met dienst 1 zelf of met dienst 2 tellen niet mee.
    - De pauze geldt per dag (één keer, bij het langste deel), niet per dienst.
    - Zelf ingevulde uren van dienst 1 naast een dienst 2 die het dagtotaal zijn (zie
      _is_dagtotaal) vervallen.
    Elke gecorrigeerde dienst komt in het logboek. Geeft het aantal gecorrigeerde diensten;
    commit doet de aanroeper.
    """
    from sqlalchemy.orm import joinedload

    from . import logboek
    from .urenberekening import formatteer_uren

    per_dag: dict[tuple[int, date], dict[int, Dienst]] = {}
    for dienst in Dienst.query.options(joinedload(Dienst.medewerker)).all():
        per_dag.setdefault((dienst.medewerker_id, dienst.datum), {})[dienst.volgnummer] = dienst
    dagen = [(d.get(1), d.get(2)) for d in per_dag.values()
             if (d.get(2) is not None and not d[2].is_leeg)
             or (d.get(1) is not None and d[1].opmerking_begin and d[1].opmerking_eind)]
    if not dagen:
        return 0
    datums = [(d1 or d2).datum for d1, d2 in dagen]
    context = UrenContext(min(datums), max(datums))
    gecorrigeerd = 0
    for dienst1, dienst2 in dagen:
        reden = "de pauze geldt per dag, niet per dienst"
        if dienst1 is not None and dienst1.opmerking_begin and context.opmerkingtijden_meetellen \
                and opmerking_valt_samen(dienst1, dienst2):
            reden = "opmerkingtijden vallen samen met een dienst van die dag"
        if dienst1 is not None and dienst1.uren_handmatig is not None and dienst2 is not None \
                and not dienst2.is_leeg and _is_dagtotaal(dienst1, dienst2, context):
            dienst1.uren_handmatig = None
            reden = "zelf ingevulde uren waren het totaal van de dag, met dienst 2 erbij"
        for dienst, nieuw in zip((dienst1, dienst2), dag_uren(dienst1, dienst2, context), strict=True):
            if dienst is None or dienst.uren_berekend == nieuw:
                continue
            oud = dienst.uren_berekend
            dienst.uren_berekend = nieuw
            dienst.versie = (dienst.versie or 0) + 1
            gecorrigeerd += 1
            logboek.log("Uren gecorrigeerd", f"Gecorrigeerd: {reden}", datum=dienst.datum,
                        medewerker=dienst.medewerker.naam, veld=VELD_UREN[dienst.volgnummer],
                        oud=formatteer_uren(oud), nieuw=formatteer_uren(nieuw), gebruiker="systeem")
    return gecorrigeerd


VELD_UREN = {1: "uren", 2: "dienst 2: uren"}


def diensten_met_afwijkende_std_tijden(code: Dienstcode, vanaf: date) -> list[Dienst]:
    """Toekomstige diensten met deze code waarvan de tijden niet de standaard zijn."""
    diensten = Dienst.query.filter(
        Dienst.dienstcode_id == code.id, Dienst.datum >= vanaf
    ).all()
    return [d for d in diensten if (d.begin, d.eind) != (code.std_begin, code.std_eind)]


def pas_std_tijden_toe(code: Dienstcode, vanaf: date) -> list[Dienst]:
    """Zet de standaardtijden van de code op alle diensten vanaf `vanaf`.

    Ook handmatige tijden worden overschreven (de beheerder heeft dit expliciet
    bevestigd). Geeft de gewijzigde diensten terug; commit doet de aanroeper.
    """
    diensten = diensten_met_afwijkende_std_tijden(code, vanaf)
    if not diensten:
        return []
    context = UrenContext(min(d.datum for d in diensten), max(d.datum for d in diensten))
    from . import logboek

    for dienst in diensten:
        oud = dienst_samenvatting(dienst)
        dienst.begin = code.std_begin
        dienst.eind = code.std_eind
        dienst.tijden_handmatig = False
        dienst.versie += 1
        dienst.uren_berekend = uren_voor(dienst, context)
        logboek.log("Rooster gewijzigd", f"Standaardtijden code {code.nummer} toegepast", datum=dienst.datum,
                    medewerker=dienst.medewerker.naam, veld=logveld(dienst.volgnummer), oud=oud,
                    nieuw=dienst_samenvatting(dienst))
    return diensten


def dienst_tekst(code: int | None, dienstnaam: str, begin: str | None, eind: str | None,
                 uren_handmatig: float | None = None, opmerking: str = "", opm_begin: str | None = None,
                 opm_eind: str | None = None) -> str:
    """Korte tekst voor het logboek, bijv. '4 VW Vroeg · 07:15-15:45 · opmerking BHV'."""
    delen = [" ".join(str(x) for x in (code, dienstnaam) if x)]
    if begin or eind:
        delen.append(f"{begin or ''}-{eind or ''}")
    if uren_handmatig is not None:
        delen.append(f"{uren_handmatig:g} uur")
    if opmerking or opm_begin or opm_eind:
        tijden = f"{opm_begin or ''}-{opm_eind or ''}"
        delen.append(f"opmerking {opmerking} {tijden}".strip(" -"))
    return " · ".join(d for d in delen if d)


def logveld(volgnummer: int) -> str:
    """Veldnaam in het logboek voor een hele dienst ('dienst' of 'dienst 2')."""
    return "dienst 2" if volgnummer == 2 else "dienst"


def dienst_samenvatting(dienst: Dienst | None) -> str:
    """dienst_tekst van een dienst ('' voor geen of een lege dienst)."""
    if dienst is None or dienst.is_leeg:
        return ""
    # Het ID is leidend: bij week kopiëren wordt alleen dienstcode_id gezet
    code = dienst.dienstcode if dienst.dienstcode_id is not None else None
    if dienst.dienstcode_id is not None and (code is None or code.id != dienst.dienstcode_id):
        code = db.session.get(Dienstcode, dienst.dienstcode_id)
    naam = dienst.dienstnaam_override or (code.omschrijving if code else "")
    return dienst_tekst(code.nummer if code else None, naam,
                        dienst.begin, dienst.eind, dienst.uren_handmatig, dienst.opmerking_tekst,
                        dienst.opmerking_begin, dienst.opmerking_eind)


def markeer_bijgewerkt() -> None:
    """Onthoud het tijdstip van de laatste roosterwijziging (voor de kalender)."""
    instellingen.schrijf("laatst_bijgewerkt", klok.nu().strftime("%d-%m-%Y %H:%M:%S"))
