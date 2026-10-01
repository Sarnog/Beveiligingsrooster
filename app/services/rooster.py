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


def uren_voor(dienst: Dienst, context: UrenContext) -> float | None:
    """Uren van één dienst: de tijdenregel, plus eventueel de opmerkingtijden.

    De pauzestaffel geldt per dienst, en apart voor de opmerkingtijden.

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
