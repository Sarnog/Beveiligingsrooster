"""Gedeelde mechaniek voor wijzigingen in bulk: de Excel-import en roosterpatronen (sinds 1.6.0).

Beide werken in twee stappen: eerst een droogloop die per dienst (medewerker, datum,
volgnummer) een Actie bepaalt (nieuw / vervangen / verwijderd / gelijk / overgeslagen), daarna
voert voer_uit() precies die acties uit: zoals het rooster zelf (standaardtijden van de code,
uren, versie, ruim_dag_op, een logboekregel per gewijzigde dienst met oud en nieuw) en met
Google-synchronisatie alleen voor de geraakte medewerkers (plan_agenda).
Er wordt hier nergens gecommit; dat doet de aanroeper (alles of niets).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ..extensions import db
from ..models import Dienst, Dienstcode, Medewerker
from . import logboek, sync_planning
from .rooster import UrenContext, dienst_tekst, logveld, uren_voor
from .weekrooster import LEGE_DIENST, ruim_dag_op

SOORTEN = ("nieuw", "vervangen", "verwijderd", "gelijk", "overgeslagen")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Inhoud:
    """De inhoud van één dienst, om bestaand en nieuw te vergelijken."""

    code: int | None
    dienstnaam: str  # dienstnaam_override
    begin: str | None
    eind: str | None
    opmerking: str
    opm_begin: str | None
    opm_eind: str | None
    uren_handmatig: float | None

    @classmethod
    def van_dienst(cls, dienst: Dienst) -> "Inhoud":
        return cls(dienst.dienstcode.nummer if dienst.dienstcode else None,
                   dienst.dienstnaam_override or "", dienst.begin, dienst.eind,
                   dienst.opmerking_tekst or "", dienst.opmerking_begin, dienst.opmerking_eind,
                   dienst.uren_handmatig)

    @property
    def heeft_dienst(self) -> bool:
        """Code, dienstnaam, tijden of uren (de opmerking telt hier niet)."""
        return bool(self.code is not None or self.dienstnaam or self.begin or self.eind
                    or self.uren_handmatig is not None)

    def samenvatting(self) -> str:
        """Korte tekst voor het logboek (zie rooster.dienst_tekst)."""
        return dienst_tekst(self.code, self.dienstnaam, self.begin, self.eind, self.uren_handmatig,
                            self.opmerking, self.opm_begin, self.opm_eind)


@dataclass
class Actie:
    """Wat er met één dienst (medewerker, datum, volgnummer) gebeurt.

    sleutel: hoe de aanroeper de medewerker kent (de import: de naam uit het bestand;
    roosterpatronen: het medewerker-ID).
    """

    sleutel: object
    datum: date
    volgnummer: int
    soort: str  # zie SOORTEN
    bestaand: Dienst | None = None
    nieuw: Inhoud | None = None


@dataclass
class Telling:
    nieuw: int = 0
    vervangen: int = 0
    verwijderd: int = 0
    gelijk: int = 0
    overgeslagen: int = 0

    def tel(self, soort: str) -> None:
        setattr(self, soort, getattr(self, soort) + 1)


def som(tellingen) -> Telling:
    totaal = Telling()
    for telling in tellingen:
        for soort in SOORTEN:
            setattr(totaal, soort, getattr(totaal, soort) + getattr(telling, soort))
    return totaal


def vul_dienst(dienst: Dienst, inhoud: Inhoud | None, codes: dict[int, Dienstcode]) -> None:
    """Zet de inhoud in een (nieuwe of bestaande) dienst; None = leegmaken."""
    if inhoud is None:
        for kolom, leeg in LEGE_DIENST.items():
            setattr(dienst, kolom, leeg)
        dienst.dienstcode = None
        return
    code = codes.get(inhoud.code) if inhoud.code is not None else None
    dienst.dienstcode = code
    dienst.dienstcode_id = code.id if code else None
    dienst.dienstnaam_override = inhoud.dienstnaam
    dienst.begin, dienst.eind = inhoud.begin, inhoud.eind
    dienst.tijden_handmatig = bool(code and (inhoud.begin, inhoud.eind) != (code.std_begin, code.std_eind))
    dienst.opmerking_tekst = inhoud.opmerking
    dienst.opmerking_begin, dienst.opmerking_eind = inhoud.opm_begin, inhoud.opm_eind
    dienst.uren_handmatig = inhoud.uren_handmatig


def voer_uit(acties: list[Actie], medewerker_van: Callable[[Actie], Medewerker], logactie: str,
             details: Callable[[Actie], str]) -> tuple[dict[str, int], dict[Medewerker, set[date]]]:
    """Voer de acties uit (gelijk en overgeslagen: niets). Geeft (aantal per soort, geraakt).

    geraakt: medewerker -> dagen waarop een dienst met een Google-afspraak veranderde (voor
    plan_agenda). Lege regels gaan weg via ruim_dag_op; met een Google-afspraak blijven ze
    (leeg) staan tot de worker de afspraak verwijderd heeft, zoals in het rooster.
    """
    codes = {c.nummer: c for c in Dienstcode.query.all()}
    uit_te_voeren = [a for a in acties if a.soort in ("nieuw", "vervangen", "verwijderd")]
    context = UrenContext(min(a.datum for a in uit_te_voeren), max(a.datum for a in uit_te_voeren)) \
        if uit_te_voeren else None
    aantallen = dict.fromkeys(SOORTEN, 0)
    geraakt: dict[Medewerker, set[date]] = {}
    opruimen: set[tuple[int, date]] = set()
    for actie in acties:
        aantallen[actie.soort] += 1
        if actie not in uit_te_voeren:
            continue
        medewerker = medewerker_van(actie)
        dienst = actie.bestaand
        oud = Inhoud.van_dienst(dienst).samenvatting() if dienst and not dienst.is_leeg else ""
        if dienst is None:
            dienst = Dienst(medewerker_id=medewerker.id, datum=actie.datum, volgnummer=actie.volgnummer,
                            versie=0, google_event_id="")
            db.session.add(dienst)
        vul_dienst(dienst, actie.nieuw, codes)
        dienst.uren_berekend = uren_voor(dienst, context)
        dienst.versie = (dienst.versie or 0) + 1
        logboek.log(logactie, details(actie), datum=actie.datum, medewerker=medewerker.naam,
                    veld=logveld(actie.volgnummer), oud=oud,
                    nieuw=actie.nieuw.samenvatting() if actie.nieuw else "")
        opruimen.add((medewerker.id, actie.datum))
        dagen = geraakt.setdefault(medewerker, set())
        if dienst.google_event_id:
            dagen.add(actie.datum)
    db.session.flush()
    for medewerker_id, datum in opruimen:
        ruim_dag_op(medewerker_id, datum)
    return aantallen, geraakt


def plan_agenda(geraakt: dict[Medewerker, set[date]], waarom: str) -> None:
    """Alleen de geraakte medewerkers opnieuw in Google Agenda zetten (na de commit).

    geraakt: medewerker -> dagen waarop een dienst met een Google-afspraak veranderde.
    Eén volledige synchronisatie doet de sync-periode; dagen daarbuiten met een afspraak
    krijgen een eigen taak (een lege regel met een afspraak moet nog opgeruimd worden).
    De wijziging zelf is al opgeslagen: een fout hier mag niet als 'mislukt' gelden.
    """
    from .sync import sync_periode

    van, tot = sync_periode()
    for medewerker, dagen in geraakt.items():
        try:
            sync_planning.plan_volledig(medewerker)
            for dag in sorted(dagen):
                if not van <= dag <= tot:
                    sync_planning.plan_dag(medewerker, dag, commit=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("Agenda-synchronisatie na %s niet gepland voor %s; gebruik Beheer → Google "
                          "Agenda → Volledig synchroniseren", waarom, medewerker.naam)
