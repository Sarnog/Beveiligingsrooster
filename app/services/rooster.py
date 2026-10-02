"""Roosterlogica: uren van diensten berekenen en bijwerken."""

from datetime import date

from ..extensions import db
from ..models import Dienst, Dienstcode
from . import instellingen, klok
from .feestdagen import feestdagen_in_periode
from .tijden import tijd_naar_minuten
from .urenberekening import bereken_uren, dagfactor

_ZOEKEN = object()  # uren_voor: dienst 2 van de dag zelf opzoeken


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


def opmerking_is_tweede_dienst(dienst, tweede: Dienst | None) -> bool:
    """De opmerkingtijden van dienst 1 vallen (deels) samen met dienst 2.

    Zo stond een tweede dienst vóór versie 1.4.0 (en in het oude Excel) in het rooster:
    als opmerking met tijden, bijv. 'Soc. Veiligh. OB 13:00-17:00'. Wordt dat daarna een
    echte dienst 2, dan telt dat tijdvak alleen nog bij dienst 2 (anders telt het dubbel).
    """
    return tweede is not None and tijden_overlappen(
        dienst.opmerking_begin, dienst.opmerking_eind, tweede.begin, tweede.eind)


def _tweede_dienst_van(dienst) -> Dienst | None:
    """Dienst 2 van dezelfde dag (alleen voor een opgeslagen dienst 1)."""
    if getattr(dienst, "volgnummer", None) != 1 or not getattr(dienst, "medewerker_id", None):
        return None
    with db.session.no_autoflush:
        return Dienst.query.filter_by(medewerker_id=dienst.medewerker_id, datum=dienst.datum,
                                      volgnummer=2).first()


def uren_voor(dienst: Dienst, context: UrenContext, tweede=_ZOEKEN) -> float | None:
    """Uren van één dienst: de tijdenregel, plus eventueel de opmerkingtijden.

    De pauzestaffel geldt per dienst, en apart voor de opmerkingtijden. Vallen de
    opmerkingtijden samen met dienst 2 van die dag, dan tellen ze niet mee (zie
    opmerking_is_tweede_dienst). tweede: dienst 2 als die al bekend is (scheelt een query).

    Zelf ingevulde uren (uren_handmatig) gaan altijd voor, zonder toeslagfactor:
    zo werkte het ook in Excel als je een getal in de urenkolom typte.
    """
    if dienst.uren_handmatig is not None:
        return dienst.uren_handmatig
    factor = context.factor(dienst.datum)
    uren = bereken_uren(dienst.begin, dienst.eind, factor, context.pauze)
    if context.opmerkingtijden_meetellen:
        extra = bereken_uren(dienst.opmerking_begin, dienst.opmerking_eind, factor, context.pauze)
        if extra is not None:
            if tweede is _ZOEKEN:
                tweede = _tweede_dienst_van(dienst)
            if not opmerking_is_tweede_dienst(dienst, tweede):
                uren = (uren or 0) + extra
    return uren


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
    tweede = {(d.medewerker_id, d.datum): d for d in diensten if d.volgnummer == 2}
    gewijzigd = 0
    for dienst in diensten:
        nieuw = uren_voor(dienst, context, tweede.get((dienst.medewerker_id, dienst.datum))
                          if dienst.volgnummer == 1 else None)
        if nieuw != dienst.uren_berekend:
            dienst.uren_berekend = nieuw
            gewijzigd += 1
    db.session.commit()
    return gewijzigd


def _is_dagtotaal(dienst1: Dienst, dienst2: Dienst, context: UrenContext) -> bool:
    """Zijn de zelf ingevulde uren van dienst 1 het totaal van de hele dag?

    Zo kwam het uit de import (dienst plus een training op de opmerkingregel, zoals in Excel)
    of van vóór versie 1.6.0: dienst 1 + dienst 2, of dienst 1 + de opmerkingtijden die
    samenvallen met dienst 2. Andere eigen uren laten we staan (die zijn bewust zo gezet).
    """
    factor = context.factor(dienst1.datum)
    eigen = bereken_uren(dienst1.begin, dienst1.eind, factor, context.pauze) or 0
    totalen = [eigen + (bereken_uren(dienst2.begin, dienst2.eind, factor, context.pauze) or 0)]
    if opmerking_is_tweede_dienst(dienst1, dienst2):
        totalen.append(eigen + (bereken_uren(dienst1.opmerking_begin, dienst1.opmerking_eind, factor,
                                             context.pauze) or 0))
    return any(abs(dienst1.uren_handmatig - totaal) < 0.01 for totaal in totalen)


def herstel_tweede_diensten() -> int:
    """Controleer alle dagen met een tweede dienst en corrigeer dubbel getelde uren (eenmalig, 1.8.2).

    - Zelf ingevulde uren van dienst 1 die het dagtotaal zijn (zie _is_dagtotaal) vervallen.
    - Opmerkingtijden die samenvallen met dienst 2 tellen niet meer mee (zie uren_voor).
    Elke gecorrigeerde dienst komt in het logboek. Geeft het aantal gecorrigeerde dagen;
    commit doet de aanroeper.
    """
    from sqlalchemy.orm import joinedload

    from . import logboek
    from .urenberekening import formatteer_uren

    tweede = {(d.medewerker_id, d.datum): d for d in Dienst.query.filter_by(volgnummer=2).all()
              if not d.is_leeg}
    if not tweede:
        return 0
    eerste = (Dienst.query.options(joinedload(Dienst.medewerker))
              .filter(Dienst.volgnummer == 1, Dienst.datum >= min(d for _, d in tweede),
                      Dienst.datum <= max(d for _, d in tweede)).all())
    context = UrenContext(min(d for _, d in tweede), max(d for _, d in tweede))
    gecorrigeerd = 0
    for dienst1 in eerste:
        dienst2 = tweede.get((dienst1.medewerker_id, dienst1.datum))
        if dienst2 is None:
            continue
        oud = dienst1.uren_berekend
        reden = "opmerkingtijden vallen samen met dienst 2"
        if dienst1.uren_handmatig is not None and _is_dagtotaal(dienst1, dienst2, context):
            dienst1.uren_handmatig = None
            reden = "zelf ingevulde uren waren het totaal van de dag, met dienst 2 erbij"
        nieuw = uren_voor(dienst1, context, dienst2)
        if nieuw == oud:
            continue
        dienst1.uren_berekend = nieuw
        dienst1.versie = (dienst1.versie or 0) + 1
        gecorrigeerd += 1
        logboek.log("Uren gecorrigeerd", f"Dubbel geteld: {reden}", datum=dienst1.datum,
                    medewerker=dienst1.medewerker.naam, veld="uren", oud=formatteer_uren(oud),
                    nieuw=formatteer_uren(nieuw), gebruiker="systeem")
    return gecorrigeerd


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
