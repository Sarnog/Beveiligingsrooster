"""Roosterpatronen en sjablonen (Beheer → Roosterpatronen, sinds 1.6.0).

Een patroon is een cyclus van N weken (1..12, standaard 8) met per dag een code-cel zoals in
het code-raster: '4', twee diensten als '4/7', leeg = vrij. De cellen worden gecontroleerd met
dezelfde regels als het raster (splits_codes / _lees_code: bestaande, actieve codes, hooguit
twee diensten; de blanco-code betekent vrij).

Uitrollen: voor één of meer medewerkers, van een startweek t/m een einddatum, elk met een eigen
startpositie in de cyclus (zo draaien collega's elk een andere week van hetzelfde patroon).
De week van een dag in het patroon: (weken sinds de startweek + startpositie - 1) mod N + 1.
- modus 'overschrijven': elke dag krijgt precies het patroon (een vrije dag wist de dienst);
  'aanvullen': alleen dagen zonder dienst krijgen het patroon.
- feestdagen: 'invullen' of 'overslaan' (dan blijft de feestdag zoals hij is).
- een gearchiveerde medewerker krijgt niets op of na de archiefdatum.
Een patroon gaat over de dienst (code, naam, tijden, zelf ingevulde uren). De opmerking
(regel a en b) hoort bij de dag en blijft staan; een dag met alleen een opmerking telt als leeg.

Werkwijze als de import: eerst een droogloop (effect), dan pas_toe met precies dezelfde
acties (roosteracties.voer_uit): standaardtijden van de code, uren, versie, ruim_dag_op, logboek
per gewijzigde dienst en Google-synchronisatie alleen voor de geraakte medewerkers. Alles in
één transactie, met vooraf een back-up 'voor-patroon'.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Dienst, Dienstcode, Medewerker, RoosterPatroon, RoosterPatroonDag
from . import backup, logboek
from .feestdagen import feestdagen_in_periode, zorg_voor_jaar
from .kalender import MAX_JAAR, MIN_JAAR
from .rooster import markeer_bijgewerkt
from .roosteracties import SOORTEN, Actie, Inhoud, Telling, plan_agenda, som, voer_uit
from .weekrooster import CelFout, _lees_code, matrix_code, splits_codes

MAX_WEKEN = 12
STANDAARD_WEKEN = 8
MAX_NAAM = 60
MAX_UITROL_WEKEN = 106  # ruim twee jaar per keer
MODUS_OVERSCHRIJVEN = "overschrijven"
MODUS_AANVULLEN = "aanvullen"
MODI = {
    MODUS_OVERSCHRIJVEN: "Overschrijven: elke dag precies het patroon (een vrije dag wist de dienst)",
    MODUS_AANVULLEN: "Alleen lege dagen aanvullen (niets overschrijven)",
}
FEESTDAG_INVULLEN = "invullen"
FEESTDAG_OVERSLAAN = "overslaan"
FEESTDAG_KEUZES = {
    FEESTDAG_INVULLEN: "Feestdagen gewoon invullen",
    FEESTDAG_OVERSLAAN: "Feestdagen overslaan (blijven zoals ze zijn)",
}
log = logging.getLogger(__name__)


class PatroonFout(ValueError):
    """Ongeldig patroon of ongeldige keuzes voor het uitrollen."""


# ---------------------------------------------------------------------------
# Patronen maken, wijzigen en verwijderen
# ---------------------------------------------------------------------------

def normaliseer_cel(tekst: str | None) -> str:
    """'4', '4 / 7', '4+7' -> '4', '4/7'; leeg of de blanco-code -> '' (vrij). Ongeldig: CelFout."""
    delen = splits_codes(tekst or "")  # zelfde controle als het code-raster
    codes = [str(code.nummer) if (code := _lees_code(deel)) else "" for deel in delen]
    return "/".join(codes).rstrip("/")


def lees_weken(waarde) -> int | None:
    """Aantal weken 1..MAX_WEKEN uit een formulier, of None."""
    try:
        weken = int(str(waarde).strip())
    except ValueError:
        return None
    return weken if 1 <= weken <= MAX_WEKEN else None


def controleer(naam: str, weken, cellen: dict, patroon: RoosterPatroon | None = None) \
        -> tuple[str, int | None, dict[tuple[int, int], str], list[str]]:
    """(naam, weken, schone cellen, foutmeldingen). Lege cellen (vrij) vallen weg."""
    fouten = []
    naam = (naam or "").strip()[:MAX_NAAM]
    if not naam:
        fouten.append("Vul een naam in voor het patroon.")
    else:
        bestaand = RoosterPatroon.query.filter(db.func.lower(RoosterPatroon.naam) == naam.lower()).first()
        if bestaand is not None and bestaand is not patroon:
            fouten.append(f"Er bestaat al een patroon met de naam '{bestaand.naam}'.")
    aantal = lees_weken(weken)
    if aantal is None:
        fouten.append(f"Een patroon heeft 1 t/m {MAX_WEKEN} weken.")
    schoon = {}
    for (week, dag), tekst in sorted(cellen.items()):
        if not (tekst or "").strip():
            continue
        if not 0 <= dag <= 6:
            fouten.append(f"Ongeldige dag ({dag}).")
            continue
        if aantal is not None and not 1 <= week <= aantal:
            fouten.append(f"Het patroon heeft {aantal} weken; week {week} valt erbuiten.")
            continue
        try:
            cel = normaliseer_cel(tekst)
        except CelFout as fout:
            fouten.append(f"Week {week}, {DAGNAMEN[dag]}: {fout}")
            continue
        if cel:
            schoon[(week, dag)] = cel
    return naam, aantal, schoon, fouten


DAGNAMEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


def sla_op(patroon: RoosterPatroon | None, naam: str, weken, cellen: dict) \
        -> tuple[RoosterPatroon | None, list[str]]:
    """Nieuw patroon (patroon=None) of wijzigen. Geeft (patroon, []) of (None, fouten); commit."""
    naam, aantal, schoon, fouten = controleer(naam, weken, cellen, patroon)
    if fouten:
        return None, fouten
    nieuw = patroon is None
    if nieuw:
        patroon = RoosterPatroon(naam=naam, weken=aantal)
        db.session.add(patroon)
    oud = "" if nieuw else beschrijving(patroon)
    patroon.naam, patroon.weken = naam, aantal
    patroon.dagen = [RoosterPatroonDag(week=w, dag=d, codes=c) for (w, d), c in sorted(schoon.items())]
    db.session.flush()
    logboek.log("Roosterpatroon opgeslagen", "nieuw" if nieuw else "gewijzigd", veld=naam, oud=oud,
                nieuw=beschrijving(patroon))
    db.session.commit()
    return patroon, []


def beschrijving(patroon: RoosterPatroon) -> str:
    """Voor het logboek: 'W1: ma 4, di 4/7; W2: ...'."""
    per_week: dict[int, list[str]] = {}
    for dag in patroon.dagen:
        per_week.setdefault(dag.week, []).append(f"{DAGNAMEN[dag.dag][:2]} {dag.codes}")
    regels = "; ".join(f"W{w}: {', '.join(d)}" for w, d in sorted(per_week.items()))
    return f"{patroon.weken} weken" + (f" – {regels}" if regels else "")


def verwijder(patroon: RoosterPatroon) -> None:
    logboek.log("Roosterpatroon verwijderd", veld=patroon.naam, oud=beschrijving(patroon))
    db.session.delete(patroon)
    db.session.commit()


def sjabloon(medewerker: Medewerker, van_maandag: date, tot_maandag: date) \
        -> tuple[dict[tuple[int, int], str], int, list[str]]:
    """Een patroon uit het rooster: de weken van van_maandag t/m tot_maandag van één medewerker.

    Geeft (cellen, aantal weken, waarschuwingen). Een dienst zonder code (vrije dienstnaam)
    kan niet in een patroon en telt als vrij; een code die niet meer bestaat ook.
    """
    if tot_maandag < van_maandag:
        raise PatroonFout("De laatste week ligt vóór de eerste week.")
    weken = (tot_maandag - van_maandag).days // 7 + 1
    if weken > MAX_WEKEN:
        raise PatroonFout(f"Een patroon heeft hooguit {MAX_WEKEN} weken; je koos er {weken}.")
    per_dag: dict[date, dict[int, Dienst]] = {}
    for dienst in (Dienst.query.options(joinedload(Dienst.dienstcode))
                   .filter(Dienst.medewerker_id == medewerker.id, Dienst.datum >= van_maandag,
                           Dienst.datum <= tot_maandag + timedelta(days=6)).all()):
        if not dienst.is_leeg:
            per_dag.setdefault(dienst.datum, {})[dienst.volgnummer] = dienst
    cellen, waarschuwingen = {}, []
    for dag, diensten in sorted(per_dag.items()):
        if any(d.dienstcode is None and Inhoud.van_dienst(d).heeft_dienst for d in diensten.values()):
            waarschuwingen.append(f"{dag:%d-%m-%Y}: een dienst zonder code (vrije dienstnaam) telt als vrij.")
        try:
            cel = normaliseer_cel(matrix_code(diensten.get(1), diensten.get(2)))
        except CelFout as fout:
            waarschuwingen.append(f"{dag:%d-%m-%Y}: {fout} (telt als vrij).")
            continue
        if cel:
            cellen[((dag - van_maandag).days // 7 + 1, dag.weekday())] = cel
    return cellen, weken, waarschuwingen


# ---------------------------------------------------------------------------
# Uitrollen: keuzes, droogloop (effect) en toepassen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UitrolKeuzes:
    """Wat het uitrollen doet. medewerkers: ((medewerker_id, startpositie 1..N), ...)."""

    patroon_id: int
    medewerkers: tuple[tuple[int, int], ...]
    van: date  # maandag van de startweek
    tot: date  # laatste dag (inclusief)
    modus: str = MODUS_OVERSCHRIJVEN
    feestdagen: str = FEESTDAG_INVULLEN

    def controleer(self, patroon: RoosterPatroon) -> list[str]:
        """Foutmeldingen (leeg = in orde). Wordt bij het toepassen opnieuw gedaan."""
        fouten = []
        if patroon is None or patroon.id != self.patroon_id:
            return ["Onbekend patroon."]
        if not self.medewerkers:
            fouten.append("Kies minstens één medewerker.")
        ids = [mid for mid, _ in self.medewerkers]
        if len(set(ids)) != len(ids):
            fouten.append("Elke medewerker mag maar één keer gekozen worden.")
        bekend = {m.id for m in Medewerker.query.filter(Medewerker.id.in_(ids))} if ids else set()
        if onbekend := [str(mid) for mid in ids if mid not in bekend]:
            fouten.append("Onbekende medewerker(s): " + ", ".join(onbekend) + ".")
        if any(not 1 <= positie <= patroon.weken for _, positie in self.medewerkers):
            fouten.append(f"De startpositie in de cyclus is 1 t/m {patroon.weken}.")
        if not (MIN_JAAR <= self.van.year <= MAX_JAAR and MIN_JAAR <= self.tot.year <= MAX_JAAR):
            fouten.append(f"Kies een periode tussen {MIN_JAAR} en {MAX_JAAR}.")
        elif self.van.weekday() != 0:
            fouten.append("De startweek moet op een maandag beginnen.")
        elif self.tot < self.van:
            fouten.append("De einddatum moet op of na de startweek liggen.")
        elif (self.tot - self.van).days >= 7 * MAX_UITROL_WEKEN:
            fouten.append(f"Rol hooguit {MAX_UITROL_WEKEN} weken in één keer uit.")
        if self.modus not in MODI:
            fouten.append("Kies een geldige modus (overschrijven of aanvullen).")
        if self.feestdagen not in FEESTDAG_KEUZES:
            fouten.append("Kies wat er met feestdagen gebeurt (invullen of overslaan).")
        for (week, dag), cel in sorted(patroon.cellen().items()):  # codes kunnen inmiddels weg zijn
            try:
                normaliseer_cel(cel)
            except CelFout as fout:
                fouten.append(f"Patroon week {week}, {DAGNAMEN[dag]}: {fout}")
        return fouten

    def als_dict(self) -> dict:
        """Voor in de sessie (alleen JSON-waarden)."""
        return {"patroon_id": self.patroon_id, "medewerkers": [list(m) for m in self.medewerkers],
                "van": self.van.isoformat(), "tot": self.tot.isoformat(), "modus": self.modus,
                "feestdagen": self.feestdagen}

    def beschrijving(self, patroon: RoosterPatroon, namen: dict[int, str]) -> str:
        """Voor het logboek."""
        wie = ", ".join(f"{namen.get(mid, mid)} (start week {pos})" for mid, pos in self.medewerkers)
        return (f"patroon '{patroon.naam}', {self.van:%d-%m-%Y} t/m {self.tot:%d-%m-%Y}, modus {self.modus}, "
                f"feestdagen {self.feestdagen}; {wie}")


@dataclass
class UitrolEffect:
    per_medewerker: dict[int, Telling] = field(default_factory=dict)
    namen: dict[int, str] = field(default_factory=dict)
    acties: list[Actie] = field(default_factory=list)

    @property
    def totaal(self) -> Telling:
        return som(self.per_medewerker.values())


def patroonweek(keuzes: UitrolKeuzes, patroon: RoosterPatroon, startpositie: int, dag: date) -> int:
    """De week van het patroon (1..N) op deze dag, voor een medewerker met deze startpositie."""
    return ((dag - keuzes.van).days // 7 + startpositie - 1) % patroon.weken + 1


def _codes(cel: str, codes: dict[int, Dienstcode]) -> list[Dienstcode | None]:
    """'4/7' -> [code 4, code 7]; '/3' -> [None, code 3]; '' -> [None, None]."""
    delen = (cel.split("/") + ["", ""])[:2]
    return [codes.get(int(deel)) if deel else None for deel in delen]


def effect(patroon: RoosterPatroon, keuzes: UitrolKeuzes) -> UitrolEffect:
    """Precies wat het uitrollen met deze keuzes doet. Er wordt niets opgeslagen.

    pas_toe() voert exact deze acties uit, zodat de droogloop klopt met het resultaat.
    """
    resultaat = UitrolEffect()
    ids = [mid for mid, _ in keuzes.medewerkers]
    medewerkers = {m.id: m for m in Medewerker.query.filter(Medewerker.id.in_(ids))} if ids else {}
    codes = {c.nummer: c for c in Dienstcode.query.all()}
    cellen = patroon.cellen()
    feestdagen = set(feestdagen_in_periode(keuzes.van, keuzes.tot)) \
        if keuzes.feestdagen == FEESTDAG_OVERSLAAN else set()
    bestaand: dict[tuple[int, date], dict[int, Dienst]] = {}
    if medewerkers:
        for dienst in (Dienst.query.options(joinedload(Dienst.dienstcode))
                       .filter(Dienst.medewerker_id.in_(medewerkers), Dienst.datum >= keuzes.van,
                               Dienst.datum <= keuzes.tot).all()):
            bestaand.setdefault((dienst.medewerker_id, dienst.datum), {})[dienst.volgnummer] = dienst
    dagen = [keuzes.van + timedelta(days=i) for i in range((keuzes.tot - keuzes.van).days + 1)]

    for mid, startpositie in keuzes.medewerkers:
        medewerker = medewerkers.get(mid)
        if medewerker is None:
            continue
        telling = resultaat.per_medewerker.setdefault(mid, Telling())
        resultaat.namen[mid] = medewerker.naam
        for dag in dagen:
            gewenst = _codes(cellen.get((patroonweek(keuzes, patroon, startpositie, dag), dag.weekday()), ""),
                             codes)
            oud = bestaand.get((mid, dag), {})
            for actie in _acties_dag(mid, dag, gewenst, oud, keuzes, medewerker, dag in feestdagen):
                telling.tel(actie.soort)
                resultaat.acties.append(actie)
    return resultaat


def _acties_dag(mid: int, dag: date, gewenst: list[Dienstcode | None], oud: dict[int, Dienst],
                keuzes: UitrolKeuzes, medewerker: Medewerker, feestdag: bool) -> list[Actie]:
    """De acties voor één dag van één medewerker (dienst 1 en dienst 2)."""
    met_dienst = {vn for vn, d in oud.items() if Inhoud.van_dienst(d).heeft_dienst}
    overslaan = (not medewerker.is_zichtbaar_op(dag) or feestdag
                 or (keuzes.modus == MODUS_AANVULLEN and met_dienst))
    acties = []
    dienst1 = oud.get(1)
    opmerking = (dienst1.opmerking_tekst or "", dienst1.opmerking_begin, dienst1.opmerking_eind) \
        if dienst1 is not None else ("", None, None)
    for vn, code in enumerate(gewenst, start=1):
        dienst = oud.get(vn)
        if overslaan:
            if code is not None:
                acties.append(Actie(mid, dag, vn, "overgeslagen", dienst))
            continue
        extra = opmerking if vn == 1 else ("", None, None)  # de opmerking blijft bij de dag
        if code is not None:
            inhoud = Inhoud(code.nummer, "", code.std_begin, code.std_eind, *extra, None)
            if vn not in met_dienst:
                acties.append(Actie(mid, dag, vn, "nieuw", dienst, inhoud))
            else:
                soort = "gelijk" if Inhoud.van_dienst(dienst) == inhoud else "vervangen"
                acties.append(Actie(mid, dag, vn, soort, dienst, inhoud))
        elif vn in met_dienst:  # vrij in het patroon: de dienst gaat weg (de opmerking blijft)
            inhoud = Inhoud(None, "", None, None, *extra, None) if vn == 1 and any(extra) else None
            acties.append(Actie(mid, dag, vn, "verwijderd", dienst, inhoud))
    return acties


def pas_toe(patroon: RoosterPatroon, keuzes: UitrolKeuzes) -> dict[str, int]:
    """Rol het patroon uit, in één transactie (alles of niets), met vooraf een back-up.

    Geeft het aantal per soort (zie roosteracties.SOORTEN). Ongeldige keuzes: PatroonFout.
    """
    if fouten := keuzes.controleer(patroon):
        raise PatroonFout("Er is niets gewijzigd: " + " ".join(fouten))
    backup.maak_backup("voor-patroon")
    try:
        # Feestdagen vooraf aanmaken (zonder commit), zodat er nooit halverwege iets opgeslagen wordt
        for jaar in range(keuzes.van.year - 1, keuzes.tot.year + 2):
            zorg_voor_jaar(jaar, commit=False)
        uitkomst = effect(patroon, keuzes)
        medewerkers = {m.id: m for m in Medewerker.query.filter(Medewerker.id.in_(uitkomst.namen))}
        aantallen, geraakt = voer_uit(uitkomst.acties, lambda actie: medewerkers[actie.sleutel],
                                      "Rooster gewijzigd",
                                      lambda actie: f"Roosterpatroon '{patroon.naam}': dienst {actie.soort}")
        logboek.log("Roosterpatroon toegepast", keuzes.beschrijving(patroon, uitkomst.namen) + "; "
                    + ", ".join(f"{s}: {aantallen[s]}" for s in SOORTEN))
        markeer_bijgewerkt()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    plan_agenda(geraakt, "het roosterpatroon")
    log.info("Roosterpatroon '%s' toegepast: %s", patroon.naam, aantallen)
    return aantallen
