"""Roosterlogica: uren van diensten berekenen en bijwerken."""

from datetime import date

from ..extensions import db
from ..models import Dienst, Dienstcode
from . import instellingen, klok
from .feestdagen import feestdagen_in_periode
from .urenberekening import bereken_uren, dagfactor


class UrenContext:
    """Alles wat nodig is om uren te berekenen, één keer opgehaald.

    Zo hoeven we bij het herberekenen van duizenden diensten niet steeds
    opnieuw instellingen en feestdagen uit de database te lezen.
    """

    def __init__(self, van: date, tot: date) -> None:
        self.toeslagen = instellingen.toeslagen()
        self.opmerkingtijden_meetellen = instellingen.lees_bool("opmerkingtijden_meetellen")
        self.feestdagen = set(feestdagen_in_periode(van, tot).keys())

    def factor(self, datum: date) -> float:
        return dagfactor(
            datum,
            self.toeslagen["factor_zaterdag"],
            self.toeslagen["factor_zondag"],
            is_feestdag=datum in self.feestdagen,
            factor_feestdag=self.toeslagen["factor_feestdag"],
        )


def uren_voor(dienst: Dienst, context: UrenContext) -> float | None:
    """Uren van één dienst: de tijdenregel, plus eventueel de opmerkingtijden."""
    factor = context.factor(dienst.datum)
    uren = bereken_uren(dienst.begin, dienst.eind, factor)
    if context.opmerkingtijden_meetellen:
        extra = bereken_uren(dienst.opmerking_begin, dienst.opmerking_eind, factor)
        if extra is not None:
            uren = (uren or 0) + extra
    return uren


def bereken_dienst(dienst: Dienst, context: UrenContext | None = None) -> None:
    """Zet dienst.uren_berekend opnieuw."""
    if context is None:
        context = UrenContext(dienst.datum, dienst.datum)
    dienst.uren_berekend = uren_voor(dienst, context)


def herbereken_alle(van: date | None = None, tot: date | None = None) -> int:
    """Herbereken de uren van alle diensten (optioneel binnen een periode).

    Nodig na het wijzigen van toeslagfactoren of feestdagen. Geeft het aantal
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
    gewijzigd = 0
    for dienst in diensten:
        nieuw = uren_voor(dienst, context)
        if nieuw != dienst.uren_berekend:
            dienst.uren_berekend = nieuw
            gewijzigd += 1
    db.session.commit()
    return gewijzigd


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
    for dienst in diensten:
        dienst.begin = code.std_begin
        dienst.eind = code.std_eind
        dienst.tijden_handmatig = False
        dienst.versie += 1
        dienst.uren_berekend = uren_voor(dienst, context)
    return diensten


def markeer_bijgewerkt() -> None:
    """Onthoud het tijdstip van de laatste roosterwijziging (voor de kalender)."""
    instellingen.schrijf("laatst_bijgewerkt", klok.nu().strftime("%d-%m-%Y %H:%M:%S"))
