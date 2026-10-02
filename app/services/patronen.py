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

import hashlib
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
GEEN_BRONROOSTER = "geen diensten in de bronweken: in de doelperiode wordt alles gewist"
log = logging.getLogger(__name__)


class PatroonFout(ValueError):
    """Ongeldig patroon of ongeldige keuzes voor het uitrollen."""


class VoorbeeldVerouderd(PatroonFout):
    """Het patroon of de bronweken zijn gewijzigd sinds het getoonde voorbeeld."""


def _afdruk(inhoud) -> str:
    """Korte, vaste samenvatting (hash) van de inhoud, om in de sessie te bewaren."""
    return hashlib.sha256(repr(inhoud).encode()).hexdigest()[:32]


def _controleer_afdruk(verwacht: str | None, huidig, wat: str) -> None:
    """Weigert als de inhoud afwijkt van het voorbeeld (verwacht=None: geen controle)."""
    if verwacht is not None and verwacht != huidig():
        raise VoorbeeldVerouderd(f"Er is niets gewijzigd: {wat} is gewijzigd sinds het voorbeeld; controleer "
                                 "het bijgewerkte voorbeeld hieronder en bevestig opnieuw.")


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
    _werk_dagen_bij(patroon, schoon)
    db.session.flush()
    logboek.log("Roosterpatroon opgeslagen", "nieuw" if nieuw else "gewijzigd", veld=naam, oud=oud,
                nieuw=beschrijving(patroon))
    db.session.commit()
    return patroon, []


def _werk_dagen_bij(patroon: RoosterPatroon, schoon: dict[tuple[int, int], str]) -> None:
    """Werk de rijen per (week, dag) bij: bestaande bijwerken, nieuwe toevoegen, overbodige weg.

    Niet de hele lijst vervangen: dan voegt SQLAlchemy de nieuwe rijen toe vóór het verwijderen
    van de oude, en botst een cel die blijft staan op de unieke index uq_patroon_week_dag.
    """
    bestaand = {(d.week, d.dag): d for d in patroon.dagen}
    for sleutel, dag in bestaand.items():
        if sleutel in schoon:
            dag.codes = schoon[sleutel]
        else:
            patroon.dagen.remove(dag)  # delete-orphan
    for (week, dag), codes in sorted(schoon.items()):
        if (week, dag) not in bestaand:
            patroon.dagen.append(RoosterPatroonDag(week=week, dag=dag, codes=codes))
    patroon.dagen.sort(key=lambda d: (d.week, d.dag))


def beschrijving(patroon: RoosterPatroon) -> str:
    """Voor het logboek: 'W1: ma 4, di 4/7; W2: ...'."""
    per_week: dict[int, list[str]] = {}
    for dag in patroon.dagen:
        per_week.setdefault(dag.week, []).append(f"{DAGNAMEN[dag.dag][:2]} {dag.codes}")
    regels = "; ".join(f"W{w}: {', '.join(d)}" for w, d in sorted(per_week.items()))
    return f"{patroon.weken} weken" + (f" – {regels}" if regels else "")


def patronen_met_code(nummer: int) -> list[str]:
    """Namen (op volgorde) van de patronen die dienstcode 'nummer' gebruiken.

    Een patroon bewaart codenummers ('4/7'): na hernummeren of verwijderen van de code zou het
    stil naar een andere (of geen) dienst verwijzen. Beheer → Dienstcodes weigert dat daarom.
    """
    dagen = RoosterPatroonDag.query.options(joinedload(RoosterPatroonDag.patroon))
    namen = {dag.patroon.naam for dag in dagen if str(nummer) in dag.codes.split("/")}
    return sorted(namen, key=str.lower)


def kopieer_week(cellen: dict[tuple[int, int], str], bron: int, naar, weken: int) \
        -> dict[tuple[int, int], str]:
    """Kopie van de cellen waarin de weken in 'naar' precies gelijk zijn aan week 'bron'.

    Zo plan je één week en zet je hem in één keer in andere weken van de cyclus (bijvoorbeeld
    week 1 naar 3, 5 en 7). Een lege dag in de bronweek maakt die dag in de doelweek ook leeg.
    Ongeldige weken: PatroonFout.
    """
    if not 1 <= bron <= weken:
        raise PatroonFout(f"Kies een bronweek van 1 t/m {weken}.")
    doelen = set(naar)
    if not doelen - {bron}:
        raise PatroonFout("Kies minstens één andere week om naar te kopiëren.")
    if any(not 1 <= w <= weken for w in doelen):
        raise PatroonFout(f"Het patroon heeft {weken} weken; kies weken van 1 t/m {weken}.")
    resultaat = {k: v for k, v in cellen.items() if k[0] not in doelen or k[0] == bron}
    for dag in range(7):
        for week in doelen - {bron}:
            resultaat[(week, dag)] = cellen.get((bron, dag), "")
    return resultaat


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
    waarschuwingen: list[str] = field(default_factory=list)

    @property
    def totaal(self) -> Telling:
        return som(self.per_medewerker.values())


def _cycluspositie(van: date, weken: int, startpositie: int, dag: date) -> int:
    """De week van de cyclus (1..weken) op deze dag, als de week van 'van' startpositie is."""
    return ((dag - van).days // 7 + startpositie - 1) % weken + 1


def _codes(cel: str, codes: dict[int, Dienstcode]) -> list[Dienstcode | None]:
    """'4/7' -> [code 4, code 7]; '/3' -> [None, code 3]; '' -> [None, None]."""
    delen = (cel.split("/") + ["", ""])[:2]
    return [codes.get(int(deel)) if deel else None for deel in delen]


def vingerafdruk(patroon: RoosterPatroon) -> str:
    """De inhoud van het patroon (lengte en cellen), om het voorbeeld met het resultaat te vergelijken."""
    return _afdruk((patroon.id, patroon.weken, sorted(patroon.cellen().items())))


def effect(patroon: RoosterPatroon, keuzes: UitrolKeuzes) -> UitrolEffect:
    """Precies wat het uitrollen met deze keuzes doet. Er wordt niets opgeslagen.

    pas_toe() voert exact deze acties uit, zodat de droogloop klopt met het resultaat.
    """
    cellen = patroon.cellen()
    return _bereken(keuzes.medewerkers, lambda _medewerker: cellen, patroon.weken, keuzes.van,
                    keuzes.tot, keuzes.modus, keuzes.feestdagen)


def _bereken(plan, cellen_van, weken: int, van: date, tot: date, modus: str,
             feestdag_keuze: str) -> UitrolEffect:
    """De acties voor plan ((medewerker_id, startpositie), ...) van van t/m tot.

    cellen_van(medewerker) geeft de cellen van de cyclus voor die medewerker ((week, dag) -> cel).
    """
    resultaat = UitrolEffect()
    ids = [mid for mid, _ in plan]
    medewerkers = {m.id: m for m in Medewerker.query.filter(Medewerker.id.in_(ids))} if ids else {}
    codes = {c.nummer: c for c in Dienstcode.query.all()}
    feestdagen = set(feestdagen_in_periode(van, tot)) if feestdag_keuze == FEESTDAG_OVERSLAAN else set()
    bestaand: dict[tuple[int, date], dict[int, Dienst]] = {}
    if medewerkers:
        for dienst in (Dienst.query.options(joinedload(Dienst.dienstcode))
                       .filter(Dienst.medewerker_id.in_(medewerkers), Dienst.datum >= van,
                               Dienst.datum <= tot).all()):
            bestaand.setdefault((dienst.medewerker_id, dienst.datum), {})[dienst.volgnummer] = dienst
    dagen = [van + timedelta(days=i) for i in range((tot - van).days + 1)]

    for mid, startpositie in plan:
        medewerker = medewerkers.get(mid)
        if medewerker is None:
            continue
        cellen = cellen_van(medewerker)
        telling = resultaat.per_medewerker.setdefault(mid, Telling())
        resultaat.namen[mid] = medewerker.naam
        for dag in dagen:
            gewenst = _codes(cellen.get((_cycluspositie(van, weken, startpositie, dag), dag.weekday()), ""),
                             codes)
            oud = bestaand.get((mid, dag), {})
            for actie in _acties_dag(mid, dag, gewenst, oud, modus, medewerker, dag in feestdagen):
                telling.tel(actie.soort)
                resultaat.acties.append(actie)
    return resultaat


def _acties_dag(mid: int, dag: date, gewenst: list[Dienstcode | None], oud: dict[int, Dienst],
                modus: str, medewerker: Medewerker, feestdag: bool) -> list[Actie]:
    """De acties voor één dag van één medewerker (dienst 1 en dienst 2)."""
    met_dienst = {vn for vn, d in oud.items() if Inhoud.van_dienst(d).heeft_dienst}
    overslaan = (not medewerker.is_zichtbaar_op(dag) or feestdag
                 or (modus == MODUS_AANVULLEN and met_dienst))
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


def pas_toe(patroon: RoosterPatroon, keuzes: UitrolKeuzes, afdruk: str | None = None) -> dict[str, int]:
    """Rol het patroon uit, in één transactie (alles of niets), met vooraf een back-up.

    Geeft het aantal per soort (zie roosteracties.SOORTEN). Ongeldige keuzes: PatroonFout.
    afdruk: de vingerafdruk van het getoonde voorbeeld; wijkt het patroon daarvan af, dan
    VoorbeeldVerouderd (er verandert niets).
    """
    if fouten := keuzes.controleer(patroon):
        raise PatroonFout("Er is niets gewijzigd: " + " ".join(fouten))
    _controleer_afdruk(afdruk, lambda: vingerafdruk(patroon), "het patroon")
    return _voer_uit(keuzes, lambda: effect(patroon, keuzes), "voor-patroon", "Roosterpatroon toegepast",
                     f"Roosterpatroon '{patroon.naam}'",
                     lambda namen: keuzes.beschrijving(patroon, namen))


def _voer_uit(keuzes, bereken, backup_label: str, logactie: str, bron: str, beschrijving) -> dict[str, int]:
    """Gedeeld door uitrollen en herhalen: back-up, acties uitvoeren, logboek, één commit, agenda."""
    backup.maak_backup(backup_label)
    try:
        # Feestdagen vooraf aanmaken (zonder commit), zodat er nooit halverwege iets opgeslagen wordt
        for jaar in range(keuzes.van.year - 1, keuzes.tot.year + 2):
            zorg_voor_jaar(jaar, commit=False)
        uitkomst = bereken()
        medewerkers = {m.id: m for m in Medewerker.query.filter(Medewerker.id.in_(uitkomst.namen))}
        aantallen, geraakt = voer_uit(uitkomst.acties, lambda actie: medewerkers[actie.sleutel],
                                      "Rooster gewijzigd", lambda actie: f"{bron}: dienst {actie.soort}")
        logboek.log(logactie, beschrijving(uitkomst.namen) + "; "
                    + ", ".join(f"{s}: {aantallen[s]}" for s in SOORTEN))
        markeer_bijgewerkt()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    plan_agenda(geraakt, bron)
    log.info("%s toegepast: %s", bron, aantallen)
    return aantallen


# ---------------------------------------------------------------------------
# Rooster herhalen: een blok weken uit het rooster (alle gekozen medewerkers) herhalen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HerhaalKeuzes:
    """Herhaal de weken bron .. bron + weken - 1 van het rooster van van t/m tot.

    De cyclus loopt door vanaf de bronweken: met een 8-wekelijks rooster krijgt de week 8 weken na
    bronweek 1 weer bronweek 1, ook als 'van' midden in de cyclus valt. Per medewerker telt zijn
    eigen rooster in de bronweken (zoals een sjabloon: de code-cel, met de standaardtijden).
    """

    medewerkers: tuple[int, ...]
    bron: date  # maandag van de eerste bronweek
    weken: int
    van: date  # maandag van de eerste week die gevuld wordt
    tot: date  # laatste dag (inclusief)
    modus: str = MODUS_OVERSCHRIJVEN
    feestdagen: str = FEESTDAG_INVULLEN

    @property
    def bron_tot(self) -> date:
        """Laatste dag (zondag) van de bronweken."""
        return self.bron + timedelta(weeks=self.weken, days=-1)

    @property
    def startpositie(self) -> int:
        """De week van de cyclus (1..weken) in de week van 'van'."""
        return _cycluspositie(self.bron, self.weken, 1, self.van)

    def controleer(self) -> list[str]:
        """Foutmeldingen (leeg = in orde). Wordt bij het toepassen opnieuw gedaan."""
        fouten = []
        if not self.medewerkers:
            fouten.append("Kies minstens één medewerker.")
        if len(set(self.medewerkers)) != len(self.medewerkers):
            fouten.append("Elke medewerker mag maar één keer gekozen worden.")
        ids = list(self.medewerkers)
        bekend = {m.id for m in Medewerker.query.filter(Medewerker.id.in_(ids))} if ids else set()
        if onbekend := [str(mid) for mid in ids if mid not in bekend]:
            fouten.append("Onbekende medewerker(s): " + ", ".join(onbekend) + ".")
        if lees_weken(self.weken) is None:
            fouten.append(f"Herhaal 1 t/m {MAX_WEKEN} weken.")
            return fouten
        if not all(MIN_JAAR <= d.year <= MAX_JAAR for d in (self.bron, self.van, self.tot)):
            fouten.append(f"Kies weken tussen {MIN_JAAR} en {MAX_JAAR}.")
        elif self.bron.weekday() != 0 or self.van.weekday() != 0:
            fouten.append("De bronweek en de startweek moeten op een maandag beginnen.")
        elif self.tot < self.van:
            fouten.append("De einddatum moet op of na de startweek liggen.")
        elif (self.tot - self.van).days >= 7 * MAX_UITROL_WEKEN:
            fouten.append(f"Herhaal hooguit {MAX_UITROL_WEKEN} weken in één keer.")
        elif self.van <= self.bron_tot and self.tot >= self.bron:
            fouten.append(f"De periode om te vullen overlapt de bronweken ({self.bron:%d-%m-%Y} t/m "
                          f"{self.bron_tot:%d-%m-%Y}); kies een startweek na of vóór de bronweken.")
        if self.modus not in MODI:
            fouten.append("Kies een geldige modus (overschrijven of aanvullen).")
        if self.feestdagen not in FEESTDAG_KEUZES:
            fouten.append("Kies wat er met feestdagen gebeurt (invullen of overslaan).")
        return fouten

    def als_dict(self) -> dict:
        """Voor in de sessie (alleen JSON-waarden)."""
        return {"medewerkers": list(self.medewerkers), "bron": self.bron.isoformat(), "weken": self.weken,
                "van": self.van.isoformat(), "tot": self.tot.isoformat(), "modus": self.modus,
                "feestdagen": self.feestdagen}

    @classmethod
    def uit_dict(cls, bewaard: dict) -> "HerhaalKeuzes":
        return cls(tuple(bewaard["medewerkers"]), date.fromisoformat(bewaard["bron"]), bewaard["weken"],
                   date.fromisoformat(bewaard["van"]), date.fromisoformat(bewaard["tot"]),
                   bewaard["modus"], bewaard["feestdagen"])

    def beschrijving(self, namen: dict[int, str]) -> str:
        """Voor het logboek."""
        wie = ", ".join(str(namen.get(mid, mid)) for mid in self.medewerkers)
        return (f"bronweken {self.bron:%d-%m-%Y} t/m {self.bron_tot:%d-%m-%Y} ({self.weken} weken), "
                f"{self.van:%d-%m-%Y} t/m {self.tot:%d-%m-%Y} (start in week {self.startpositie}), "
                f"modus {self.modus}, feestdagen {self.feestdagen}; {wie}")


def met_diensten(van: date, tot: date) -> set[int]:
    """IDs van de medewerkers met minstens één dienst (niet alleen een opmerking) van van t/m tot."""
    return {d.medewerker_id for d in Dienst.query.options(joinedload(Dienst.dienstcode))
            .filter(Dienst.datum >= van, Dienst.datum <= tot) if Inhoud.van_dienst(d).heeft_dienst}


def herhaal_effect(keuzes: HerhaalKeuzes) -> UitrolEffect:
    """Precies wat het herhalen met deze keuzes doet. Er wordt niets opgeslagen."""
    waarschuwingen: list[str] = []

    def cellen_van(medewerker: Medewerker) -> dict[tuple[int, int], str]:
        laatste = keuzes.bron + timedelta(weeks=keuzes.weken - 1)
        cellen, _, meldingen = sjabloon(medewerker, keuzes.bron, laatste)
        waarschuwingen.extend(f"{medewerker.naam}, {melding}" for melding in meldingen)
        if not cellen and keuzes.modus == MODUS_OVERSCHRIJVEN:  # een vergeten collega verliest alles
            waarschuwingen.append(f"{medewerker.naam}: {GEEN_BRONROOSTER}.")
        return cellen

    # De cyclus begint bij de bronweek; vanaf 'van' rekenen met de bijbehorende startpositie
    plan = tuple((mid, keuzes.startpositie) for mid in keuzes.medewerkers)
    resultaat = _bereken(plan, cellen_van, keuzes.weken, keuzes.van, keuzes.tot, keuzes.modus,
                         keuzes.feestdagen)
    resultaat.waarschuwingen = waarschuwingen
    return resultaat


def herhaal_vingerafdruk(keuzes: HerhaalKeuzes) -> str:
    """De inhoud van de bronweken per gekozen medewerker (alle velden van elke dienst)."""
    diensten = (Dienst.query.options(joinedload(Dienst.dienstcode))
                .filter(Dienst.medewerker_id.in_(keuzes.medewerkers), Dienst.datum >= keuzes.bron,
                        Dienst.datum <= keuzes.bron_tot).all())
    regels = [((d.medewerker_id, d.datum, d.volgnummer), Inhoud.van_dienst(d)) for d in diensten
              if not d.is_leeg]
    return _afdruk(sorted(regels, key=lambda regel: regel[0]))


def herhaal_pas_toe(keuzes: HerhaalKeuzes, afdruk: str | None = None) -> dict[str, int]:
    """Herhaal de bronweken, in één transactie (alles of niets), met vooraf een back-up.

    afdruk: de vingerafdruk van het getoonde voorbeeld (zie herhaal_vingerafdruk).
    """
    if fouten := keuzes.controleer():
        raise PatroonFout("Er is niets gewijzigd: " + " ".join(fouten))
    _controleer_afdruk(afdruk, lambda: herhaal_vingerafdruk(keuzes), "het rooster in de bronweken")
    return _voer_uit(keuzes, lambda: herhaal_effect(keuzes), "voor-herhalen", "Rooster herhaald",
                     "Rooster herhaald", keuzes.beschrijving)
