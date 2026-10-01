"""Het weekrooster: gegevens ophalen en cellen wijzigen.

Een 'cel' is één veld van één medewerker op één dag:
    code        dienstcode(s) uit het code-raster: '4', of twee diensten als '4/7'
                (ook '4+7' en '4 7'); leeg wist beide diensten
    begin/eind  tijden van de dienst (regel d)
    opmerking   vrije tekst (regel a)
    opm_begin / opm_eind   tijden bij de opmerking (regel b)
Daarnaast is er per dag de 'dagopmerking' (rij 3 van het Excel-blad).

Per medewerker per dag kunnen er twee diensten zijn (volgnummer 1 en 2). Dienstnaam,
tijden en uren bestaan per dienst; de opmerking hoort bij de dag (dienst 1).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import MAX_DIENSTEN_PER_DAG, Dagopmerking, Dienst, Dienstcode, Medewerker, OpmerkingKleurregel
from . import instellingen, klok, logboek, sync_planning
from .feestdagen import feestdagen_in_periode, vakantiedagen_in_periode, zorg_voor_jaar
from .kalender import dagen_van_week
from .rooster import UrenContext, markeer_bijgewerkt, uren_voor
from .tijden import OngeldigeTijd, is_cijfers, normaliseer_tijd, tijd_naar_minuten
from .urenberekening import formatteer_uren

VELDEN = ("code", "begin", "eind", "opmerking", "opm_begin", "opm_eind", "dienstnaam", "uren")
VELD_NAMEN = {
    "code": "dienstcode", "begin": "begintijd", "eind": "eindtijd", "opmerking": "opmerking",
    "opm_begin": "opmerking begin", "opm_eind": "opmerking eind",
    "dienstnaam": "dienstnaam", "uren": "uren",
}
# Velden die dienst 2 heeft (de opmerking hoort bij de dag en staat bij dienst 1)
VELDEN_DIENST2 = ("code", "begin", "eind", "dienstnaam", "uren")
MAX_OPMERKING = 120
# Scheidingsteken tussen twee codes in het code-raster: '/', '+' of een spatie
CODE_SCHEIDING = re.compile(r"\s*[/+]\s*|\s+")
log = logging.getLogger(__name__)

# Velden van een dienst met hun 'lege' waarde (gebruikt bij week kopiëren)
LEGE_DIENST = {
    "dienstcode_id": None, "dienstnaam_override": "", "begin": None, "eind": None,
    "tijden_handmatig": False, "opmerking_tekst": "", "opmerking_begin": None,
    "opmerking_eind": None, "uren_handmatig": None,
}


class CelFout(Exception):
    """Ongeldige invoer in een cel (wordt als foutmelding bij de cel getoond)."""


class VersieConflict(Exception):
    """Iemand anders heeft deze dienst net gewijzigd (optimistic locking)."""


# ---------------------------------------------------------------------------
# Opmaak (kleuren) en omzetten naar JSON
# ---------------------------------------------------------------------------

def kleurregels() -> dict[str, OpmerkingKleurregel]:
    """Opmerking-kleurregels, op tekst (hoofdletterongevoelig)."""
    return {r.tekst.casefold(): r for r in OpmerkingKleurregel.query.all()}


def opmerking_stijl(tekst: str, regels: dict[str, OpmerkingKleurregel]) -> str:
    """CSS-stijl voor een opmerking volgens de kleurregels ('' als er geen regel is)."""
    regel = regels.get((tekst or "").strip().casefold())
    if regel is None:
        return ""
    if regel.kleur_achtergrond2:
        achtergrond = f"linear-gradient(90deg,{regel.kleur_achtergrond},{regel.kleur_achtergrond2})"
    else:
        achtergrond = regel.kleur_achtergrond
    return f"background:{achtergrond};color:{regel.kleur_tekst}"


def dienst_stijl(dienst: Dienst | None) -> str:
    """CSS-stijl van de dienstnaam (kleuren van de dienstcode)."""
    if dienst is None or dienst.dienstcode is None:
        return ""
    code = dienst.dienstcode
    return (f"background:{code.kleur_achtergrond};color:{code.kleur_tekst};"
            f"font-weight:{'bold' if code.vet else 'normal'};"
            f"font-style:{'italic' if code.cursief else 'normal'}")


def code_tekst(dienst: Dienst | None) -> str:
    """Nummer van de dienstcode als tekst ('' zonder code)."""
    return str(dienst.dienstcode.nummer) if dienst is not None and dienst.dienstcode else ""


def matrix_code(dienst1: Dienst | None, dienst2: Dienst | None) -> str:
    """Wat er in het code-raster staat: '4', of '4/7' bij twee diensten."""
    if dienst2 is None:
        return code_tekst(dienst1)
    return f"{code_tekst(dienst1)}/{code_tekst(dienst2)}"


def _achtergrond(dienst: Dienst | None) -> str:
    if dienst is None or dienst.dienstcode is None:
        return "#FFFFFF"
    return dienst.dienstcode.kleur_achtergrond


def matrix_stijl(dienst1: Dienst | None, dienst2: Dienst | None) -> str:
    """Stijl van de cel in het code-raster; bij twee diensten links/rechts gesplitst."""
    if dienst2 is None:
        return dienst_stijl(dienst1)
    tekst = (dienst1.dienstcode if dienst1 is not None and dienst1.dienstcode else dienst2.dienstcode)
    kleur_tekst = tekst.kleur_tekst if tekst is not None else "#000000"
    return (f"background:linear-gradient(90deg,{_achtergrond(dienst1)} 50%,{_achtergrond(dienst2)} 50%);"
            f"color:{kleur_tekst};font-weight:bold")


def dienst_naar_dict(dienst: Dienst | None, regels: dict | None = None) -> dict:
    """Alles wat de pagina nodig heeft om één dag van één medewerker te tonen."""
    regels = regels if regels is not None else kleurregels()
    if dienst is None:
        return {"code": "", "dienstnaam": "", "begin": "", "eind": "", "uren": "",
                "handmatig": False, "uren_handmatig": False, "opmerking": "", "opm_begin": "", "opm_eind": "",
                "versie": 0, "dienst_stijl": "", "opmerking_stijl": ""}
    return {
        "code": str(dienst.dienstcode.nummer) if dienst.dienstcode else "",
        "dienstnaam": dienst.dienstnaam,
        "begin": dienst.begin or "",
        "eind": dienst.eind or "",
        "uren": formatteer_uren(dienst.uren_berekend),
        "handmatig": bool(dienst.tijden_handmatig),
        "uren_handmatig": dienst.uren_handmatig is not None,
        "opmerking": dienst.opmerking_tekst or "",
        "opm_begin": dienst.opmerking_begin or "",
        "opm_eind": dienst.opmerking_eind or "",
        "versie": dienst.versie,
        "dienst_stijl": dienst_stijl(dienst),
        "opmerking_stijl": opmerking_stijl(dienst.opmerking_tekst, regels),
    }


def overlappen(dienst1: Dienst | None, dienst2: Dienst | None) -> bool:
    """True als de tijden van twee diensten op dezelfde dag elkaar overlappen.

    Eind vóór begin = de dienst loopt door tot na middernacht.
    """
    if dienst1 is None or dienst2 is None:
        return False
    vakken = []
    for dienst in (dienst1, dienst2):
        begin, eind = tijd_naar_minuten(dienst.begin), tijd_naar_minuten(dienst.eind)
        if begin is None or eind is None:
            return False
        vakken.append((begin, eind + 1440 if eind <= begin else eind))
    (b1, e1), (b2, e2) = vakken
    return b1 < e2 and b2 < e1


def dag_naar_dict(dienst1: Dienst | None, dienst2: Dienst | None, regels: dict | None = None) -> dict:
    """Eén dag van één medewerker: dienst 1 (met opmerking) plus eventueel dienst 2.

    De velden van dienst 1 staan direct in het resultaat (zoals vóór versie 1.4.0);
    'code' is wat er in het code-raster staat ('4' of '4/7'), 'tweede' is dienst 2
    (of None) en 'overlap' zegt of de tijden van beide diensten overlappen.
    """
    regels = regels if regels is not None else kleurregels()
    gegevens = dienst_naar_dict(dienst1, regels)
    gegevens["code"] = matrix_code(dienst1, dienst2)
    gegevens["code_stijl"] = matrix_stijl(dienst1, dienst2)
    gegevens["tweede"] = dienst_naar_dict(dienst2, regels) if dienst2 is not None else None
    gegevens["overlap"] = overlappen(dienst1, dienst2)
    return gegevens


def diensten_van_dag(medewerker_id: int, datum: date) -> tuple[Dienst | None, Dienst | None]:
    """(dienst 1, dienst 2) van een medewerker op een dag; None als die er niet is."""
    per_volgnummer = {d.volgnummer: d for d in Dienst.query.filter_by(
        medewerker_id=medewerker_id, datum=datum).all()}
    dienst2 = per_volgnummer.get(2)
    # Een lege dienst 2 (wacht alleen nog tot de agenda-afspraak weg is) telt niet mee
    return per_volgnummer.get(1), None if dienst2 is None or dienst2.is_leeg else dienst2


# ---------------------------------------------------------------------------
# Dagopmerkingen (automatisch uit feestdagen/vakanties, of handmatig)
# ---------------------------------------------------------------------------

def automatische_dagopmerkingen(van: date, tot: date, feestdagen: dict | None = None) -> dict[date, str]:
    """Feestdag gaat voor vakantie. Vakantie alleen op werkdagen (zoals in Excel).

    feestdagen: de feestdagen van deze periode, als de aanroeper die al heeft.
    """
    teksten = dict(vakantiedagen_in_periode(van, tot))
    teksten.update(feestdagen if feestdagen is not None else feestdagen_in_periode(van, tot))
    return teksten


def dagopmerkingen(dagen: list[date], feestdagen: dict | None = None) -> dict[date, dict]:
    """Per dag: {'tekst': ..., 'handmatig': bool}."""
    automatisch = automatische_dagopmerkingen(dagen[0], dagen[-1], feestdagen)
    handmatig = {
        d.datum: d for d in Dagopmerking.query.filter(
            Dagopmerking.datum >= dagen[0], Dagopmerking.datum <= dagen[-1]).all()
    }
    resultaat = {}
    for dag in dagen:
        if dag in handmatig:
            resultaat[dag] = {"tekst": handmatig[dag].tekst, "handmatig": True}
        else:
            resultaat[dag] = {"tekst": automatisch.get(dag, ""), "handmatig": False}
    return resultaat


def pas_dagopmerking_toe(datum: date, tekst: str) -> None:
    """Wijzig een dagopmerking in de sessie (opslaan of terugdraaien doet de aanroeper).

    - Tekst gelijk aan de automatische tekst: handmatige versie weghalen.
    - Lege tekst en er is een handmatige versie: weghalen (automatisch komt terug).
    - Lege tekst zonder handmatige versie maar met automatische tekst: verbergen.
    """
    tekst = (tekst or "").strip()[:MAX_OPMERKING]
    automatisch = automatische_dagopmerkingen(datum, datum).get(datum, "")
    bestaand = Dagopmerking.query.filter_by(datum=datum).first()
    oud = bestaand.tekst if bestaand else automatisch
    if bestaand is None and tekst == automatisch:
        return  # niets veranderd

    if tekst == automatisch or (tekst == "" and bestaand is not None):
        if bestaand:
            db.session.delete(bestaand)
    elif bestaand:
        bestaand.tekst = tekst
    else:
        db.session.add(Dagopmerking(datum=datum, tekst=tekst, handmatig=True))
    db.session.flush()

    logboek.log("Dagopmerking gewijzigd", datum=datum, veld="dagopmerking", oud=oud, nieuw=tekst)
    # De dagopmerking staat in de omschrijving van agenda-afspraken
    for dienst in Dienst.query.filter_by(datum=datum).all():
        sync_planning.plan_dag(dienst.medewerker, datum, commit=False)


# ---------------------------------------------------------------------------
# Weekgegevens
# ---------------------------------------------------------------------------

@dataclass
class WeekRij:
    medewerker: Medewerker
    contracturen: float | None
    dagen: list[dict] = field(default_factory=list)
    weektotaal: float = 0.0
    heeft_diensten: bool = False
    heeft_tweede: bool = False  # minstens één dag met een tweede dienst


def medewerkers_voor_periode(van: date, tot: date) -> list[Medewerker]:
    """Medewerkers in het rooster: niet gearchiveerd op de eerste dag, of met diensten."""
    met_diensten = {
        mid for (mid,) in db.session.query(Dienst.medewerker_id)
        .filter(Dienst.datum >= van, Dienst.datum <= tot).distinct()
    }
    # Contracturen in één keer meeladen (anders één query per medewerker)
    alle = (Medewerker.query.options(selectinload(Medewerker.contracturen))
            .order_by(Medewerker.volgorde, Medewerker.naam).all())
    return [m for m in alle if m.is_zichtbaar_op(van) or m.id in met_diensten]


def week_gegevens(jaar: int, week: int) -> dict:
    """Alles voor de weekpagina: dagen, dagopmerkingen en per medewerker de 7 dagen."""
    dagen = dagen_van_week(jaar, week)
    medewerkers = medewerkers_voor_periode(dagen[0], dagen[-1])
    diensten = (Dienst.query.options(joinedload(Dienst.dienstcode))
                .filter(Dienst.datum >= dagen[0], Dienst.datum <= dagen[-1]).all())
    per_sleutel = {(d.medewerker_id, d.datum): d for d in diensten if d.volgnummer == 1}
    # Een lege dienst 2 (wacht alleen nog tot de agenda-afspraak weg is) telt niet mee
    tweede = {(d.medewerker_id, d.datum): d for d in diensten if d.volgnummer == 2 and not d.is_leeg}
    regels = kleurregels()

    rijen = []
    for medewerker in medewerkers:
        rij = WeekRij(medewerker=medewerker, contracturen=medewerker.contracturen_voor(jaar))
        for dag in dagen:
            dienst = per_sleutel.get((medewerker.id, dag))
            dienst2 = tweede.get((medewerker.id, dag))
            rij.dagen.append(dag_naar_dict(dienst, dienst2, regels))
            for d in (dienst, dienst2):
                if d is not None:
                    rij.heeft_diensten = True
                    rij.weektotaal += d.uren_berekend or 0
            rij.heeft_tweede = rij.heeft_tweede or dienst2 is not None
        rijen.append(rij)

    feestdagen = feestdagen_in_periode(dagen[0], dagen[-1])  # één keer ophalen
    return {
        "jaar": jaar,
        "week": week,
        "dagen": dagen,
        "dag_iso": [dag.isoformat() for dag in dagen],  # voor de template (scheelt rekenwerk)
        "dagopmerkingen": dagopmerkingen(dagen, feestdagen),
        "feestdagen": feestdagen,
        "rijen": rijen,
        "diensten": per_sleutel,  # (medewerker_id, datum) -> dienst 1, o.a. voor de API
        "tweede_diensten": tweede,  # (medewerker_id, datum) -> dienst 2
    }


def weektotaal(medewerker_id: int, datum: date) -> float:
    """Totaal van de ISO-week waarin `datum` valt."""
    maandag = datum - timedelta(days=datum.weekday())
    som = db.session.query(db.func.sum(Dienst.uren_berekend)).filter(
        Dienst.medewerker_id == medewerker_id,
        Dienst.datum >= maandag, Dienst.datum <= maandag + timedelta(days=6),
    ).scalar()
    return float(som or 0)


# ---------------------------------------------------------------------------
# Cellen wijzigen
# ---------------------------------------------------------------------------

def _lees_code(waarde: str) -> Dienstcode | None:
    """Tekst uit het code-raster -> Dienstcode, of None voor 'geen dienst'."""
    tekst = (waarde or "").strip()
    if tekst == "":
        return None
    if not is_cijfers(tekst):
        raise CelFout(f"'{tekst}' is geen dienstcode (alleen een nummer).")
    nummer = int(tekst)
    if nummer == instellingen.blanco_code():
        return None  # blanco-code betekent: geen dienst
    code = Dienstcode.query.filter_by(nummer=nummer, actief=True).first()
    if code is None:
        raise CelFout(f"Onbekende dienstcode: {nummer}")
    return code


def splits_codes(waarde: str) -> list[str]:
    """'4/7', '4+7' of '4 7' -> ['4', '7']; '4' -> ['4']; '' -> ['']. Meer dan twee: CelFout."""
    tekst = (waarde or "").strip()
    delen = CODE_SCHEIDING.split(tekst) if tekst else [""]
    if len(delen) > MAX_DIENSTEN_PER_DAG:
        raise CelFout(f"Hooguit {MAX_DIENSTEN_PER_DAG} diensten per dag (bijvoorbeeld 4/7).")
    for deel in delen:
        _lees_code(deel)  # controleer alle codes vóór er iets gewijzigd wordt
    return delen


def _tijd(waarde: str) -> str | None:
    try:
        return normaliseer_tijd(waarde)
    except OngeldigeTijd as fout:
        raise CelFout(f"{fout}. Gebruik bijvoorbeeld 715, 7:15 of 07.15.") from fout


def begint_met_dienstnaam(tekst: str, omschrijving: str) -> bool:
    """True als de tekst de dienstnaam is, eventueel met een aanvulling erachter.

    Hoofdletterongevoelig; na de dienstnaam moet een spatie of leesteken komen
    ('VW Vroeg – kort', 'VW Vroeg (cursus)'), dus 'VW Vroegje' telt niet.
    """
    tekst, naam = tekst.casefold(), (omschrijving or "").strip().casefold()
    if not naam or not tekst.startswith(naam):
        return False
    rest = tekst[len(naam):]
    return rest == "" or not rest[0].isalnum()


def _pas_veld_toe(dienst: Dienst, veld: str, waarde: str, behoud_vrij: bool = False) -> tuple[str, str]:
    """Wijzig één veld van een dienst. Geeft (oude waarde, nieuwe waarde) als tekst.

    behoud_vrij: een lege tweede code uit '5/' laat een dienst 2 zónder code (vrije
    dienstnaam) staan; het raster toont die immers als '4/' (zie matrix_code).
    """
    if veld == "code" and dienst.volgnummer == 2 and _lees_code(waarde) is None:
        if behoud_vrij and dienst.dienstcode is None:
            oud = dienst.dienstnaam
            return oud, oud
        # Dienst 2 wissen: alles weg (ook een vrije dienstnaam en eigen tijden of uren)
        oud = code_tekst(dienst) or dienst.dienstnaam
        for kolom, leeg in LEGE_DIENST.items():
            setattr(dienst, kolom, leeg)
        dienst.dienstcode = None
        return oud, ""

    if veld == "code":
        oud = str(dienst.dienstcode.nummer) if dienst.dienstcode else ""
        code = _lees_code(waarde)
        if (str(code.nummer) if code else "") == oud:
            return oud, oud  # zelfde code: niets wijzigen (handmatige tijden blijven staan)
        dienst.dienstcode = code
        dienst.dienstcode_id = code.id if code else None
        dienst.dienstnaam_override = ""
        # Nieuwe code: standaardtijden van die code (handmatige tijden vervallen)
        dienst.begin = code.std_begin if code else None
        dienst.eind = code.std_eind if code else None
        dienst.tijden_handmatig = False
        dienst.uren_handmatig = None  # zelf ingevulde uren vervallen bij een nieuwe code
        return oud, str(code.nummer) if code else ""

    if veld in ("begin", "eind"):
        oud = getattr(dienst, veld) or ""
        setattr(dienst, veld, _tijd(waarde))
        code = dienst.dienstcode
        standaard = (code.std_begin, code.std_eind) if code else (None, None)
        # Handmatig = afwijkend van de standaardtijden van de code
        dienst.tijden_handmatig = (dienst.begin, dienst.eind) != standaard and bool(
            dienst.begin or dienst.eind)
        return oud, getattr(dienst, veld) or ""

    if veld == "opmerking":
        oud = dienst.opmerking_tekst
        dienst.opmerking_tekst = (waarde or "").strip()[:MAX_OPMERKING]
        return oud, dienst.opmerking_tekst

    if veld in ("opm_begin", "opm_eind"):
        kolom = "opmerking_begin" if veld == "opm_begin" else "opmerking_eind"
        oud = getattr(dienst, kolom) or ""
        setattr(dienst, kolom, _tijd(waarde))
        return oud, getattr(dienst, kolom) or ""

    if veld == "dienstnaam":
        # Vrije dienstnaam (zonder code), bijvoorbeeld een cursus of 'Controleronde'
        oud = dienst.dienstnaam
        tekst = (waarde or "").strip()[:60]
        if dienst.dienstcode is not None and begint_met_dienstnaam(tekst, dienst.dienstcode.omschrijving):
            # Dienstnaam met een aanvulling erachter ('VW Vroeg tot 12:00'): de code (en dus de
            # kleur en tijden) blijft, alleen de getoonde tekst krijgt de aanvulling
            dienst.dienstnaam_override = "" if tekst == dienst.dienstcode.omschrijving else tekst
            return oud, dienst.dienstnaam
        dienst.dienstcode = None
        dienst.dienstcode_id = None
        dienst.dienstnaam_override = tekst
        dienst.tijden_handmatig = bool(dienst.begin or dienst.eind)
        return oud, tekst

    if veld == "uren":
        # Zelf uren invullen (gaat voor de berekening); leeg = weer automatisch berekenen
        oud = "" if dienst.uren_handmatig is None else formatteer_uren(dienst.uren_handmatig)
        tekst = (waarde or "").strip().replace(",", ".")
        if tekst == "":
            dienst.uren_handmatig = None
            return oud, ""
        try:
            uren = float(tekst)
        except ValueError as fout:
            raise CelFout(f"'{waarde}' is geen aantal uren (bijvoorbeeld 8 of 7,5).") from fout
        if not 0 <= uren <= 24:
            raise CelFout("Uren moeten tussen 0 en 24 liggen.")
        dienst.uren_handmatig = uren
        return oud, formatteer_uren(uren)

    raise CelFout(f"Onbekend veld: {veld}")


@dataclass
class Wijziging:
    medewerker_id: int
    datum: date
    veld: str
    waarde: str
    versie: int | None = None  # None = niet controleren
    volgnummer: int = 1  # 1 = eerste dienst van de dag, 2 = tweede dienst
    # Alleen bij veld 'code' (code-raster): versie van dienst 2 (None = niet controleren)
    versie2: int | None = None
    # Lege tweede code uit '5/': een dienst 2 met een vrije dienstnaam blijft staan
    behoud_vrij: bool = False


def _veldnaam(w: Wijziging) -> str:
    """Naam van het veld voor het logboek; bij de tweede dienst met 'dienst 2: ' ervoor."""
    naam = VELD_NAMEN.get(w.veld, w.veld)
    return f"dienst 2: {naam}" if w.volgnummer == 2 else naam


def _fout(w: Wijziging, melding: str, **extra) -> dict:
    return {"mw": w.medewerker_id, "datum": w.datum.isoformat(), "veld": w.veld,
            "vn": w.volgnummer, "melding": melding, **extra}


def _splits_wijzigingen(wijzigingen: list[Wijziging]) -> tuple[list[Wijziging], list[dict]]:
    """Codes uit het code-raster ('4/7') worden twee wijzigingen: dienst 1 en dienst 2.

    Eén code zet dienst 1 en wist dienst 2; leeg wist beide. '5/' (met scheidingsteken,
    maar zonder tweede code) wist dienst 2 alleen als die een code had: een tweede dienst
    met een vrije dienstnaam staat in het raster als '4/' en blijft dan staan.
    Een ongeldige invoer (onbekende code, meer dan twee codes) wordt niet uitgevoerd.
    """
    resultaat, fouten = [], []
    for w in wijzigingen:
        if w.veld != "code" or w.volgnummer != 1:
            resultaat.append(w)
            continue
        try:
            delen = splits_codes(w.waarde)
        except CelFout as fout:
            fouten.append(_fout(w, str(fout)))
            continue
        behoud_vrij = len(delen) == MAX_DIENSTEN_PER_DAG and delen[1] == ""
        delen += [""] * (MAX_DIENSTEN_PER_DAG - len(delen))
        resultaat.append(Wijziging(w.medewerker_id, w.datum, "code", delen[0], w.versie, 1))
        resultaat.append(Wijziging(w.medewerker_id, w.datum, "code", delen[1], w.versie2, 2,
                                   behoud_vrij=behoud_vrij))
    return resultaat, fouten


def _claim(dienst: Dienst) -> None:
    """Controleer en vergrendel een bestaande dienst vóór het wijzigen (optimistic locking).

    Een voorwaardelijke UPDATE ... WHERE versie = <gelezen versie>: is de dienst intussen
    door een ander proces gewijzigd, dan raakt hij 0 rijen en volgt een VersieConflict.
    Lukt het, dan houdt SQLite de schrijfvergrendeling vast tot de commit; niemand kan de
    dienst dan nog tussendoor wijzigen (geen 'check-then-write').
    """
    tabel = Dienst.__table__
    with db.session.no_autoflush:  # eerst controleren, dan pas onze wijziging schrijven
        resultaat = db.session.execute(
            tabel.update().where(tabel.c.id == dienst.id, tabel.c.versie == dienst.versie)
            .values(versie=tabel.c.versie))
    if resultaat.rowcount != 1:
        raise VersieConflict("Iemand anders wijzigde tegelijk dezelfde dienst. "
                             "Ververs de pagina en probeer het opnieuw.")


def _pas_cellen_toe(wijzigingen: list[Wijziging]) -> tuple[set, list[dict]]:
    """Pas celwijzigingen toe in de sessie. Geeft (geraakte (mw, datum), fouten)."""
    wijzigingen, fouten = _splits_wijzigingen(wijzigingen)
    geclaimd: set[tuple[int, date, int]] = set()
    geraakt: set[tuple[int, date]] = {(f["mw"], date.fromisoformat(f["datum"])) for f in fouten}
    gecontroleerd: set[tuple[int, date, int]] = set()
    medewerkers: dict[int, Medewerker] = {}
    context_cache: dict[date, UrenContext] = {}

    for w in wijzigingen:
        sleutel = (w.medewerker_id, w.datum, w.volgnummer)
        medewerker = medewerkers.get(w.medewerker_id) or db.session.get(Medewerker, w.medewerker_id)
        if medewerker is None:
            fouten.append(_fout(w, "Onbekende medewerker."))
            continue
        medewerkers[medewerker.id] = medewerker
        if w.volgnummer not in range(1, MAX_DIENSTEN_PER_DAG + 1) or (
                w.volgnummer == 2 and w.veld not in VELDEN_DIENST2):
            fouten.append(_fout(w, "Dit veld bestaat niet bij deze dienst."))
            continue
        geraakt.add((medewerker.id, w.datum))

        dienst = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=w.datum,
                                        volgnummer=w.volgnummer).first()
        huidige_versie = dienst.versie if dienst else 0
        # Optimistic locking: alleen de eerste keer per dienst in dit verzoek controleren
        if w.versie is not None and sleutel not in gecontroleerd and w.versie != huidige_versie:
            fouten.append(_fout(w, "Deze cel is net door iemand anders gewijzigd. "
                                   "De nieuwste waarde staat nu in beeld.", conflict=True))
            continue
        gecontroleerd.add(sleutel)

        nieuw_record = dienst is None
        if nieuw_record:
            if w.veld == "code" and w.volgnummer == 2 and not w.waarde.strip():
                continue  # geen dienst 2 en die ook niet aanmaken
            # Nog niet aan de sessie toevoegen: pas als de wijziging geldig is
            dienst = Dienst(medewerker_id=medewerker.id, datum=w.datum, volgnummer=w.volgnummer,
                            versie=0, dienstnaam_override="", opmerking_tekst="",
                            tijden_handmatig=False)
        try:
            with db.session.no_autoflush:
                oud, nieuw = _pas_veld_toe(dienst, w.veld, w.waarde, w.behoud_vrij)
        except CelFout as fout:
            fouten.append(_fout(w, str(fout)))
            continue

        if oud == nieuw:
            continue
        if nieuw_record:
            db.session.add(dienst)  # tegelijk aangemaakt: de unieke index geeft een conflict
        elif sleutel not in geclaimd:
            _claim(dienst)
            geclaimd.add(sleutel)

        # Uren opnieuw berekenen
        if w.datum not in context_cache:
            context_cache[w.datum] = UrenContext(w.datum, w.datum)
        dienst.uren_berekend = uren_voor(dienst, context_cache[w.datum])
        dienst.versie = (dienst.versie or 0) + 1

        logboek.log("Rooster gewijzigd", datum=w.datum, medewerker=medewerker.naam,
                    veld=_veldnaam(w), oud=oud, nieuw=nieuw)
        sync_planning.plan_dag(medewerker, w.datum, commit=False)

        # Een helemaal lege regel ruimen we op (behalve als er nog een agenda-afspraak
        # aan hangt: die moet de worker eerst verwijderen)
        if dienst.is_leeg and not dienst.google_event_id:
            if nieuw_record:
                db.session.expunge(dienst)
            else:
                db.session.delete(dienst)
        db.session.flush()  # zodat een volgende cel van dezelfde dag deze dienst terugvindt

    return geraakt, fouten


def overlap_waarschuwingen(geraakt) -> list[dict]:
    """Dagen waarop de twee diensten van een medewerker elkaar in tijd overlappen."""
    waarschuwingen = []
    for mw, datum in sorted(geraakt, key=lambda s: (s[1], s[0])):
        dienst1, dienst2 = diensten_van_dag(mw, datum)
        if overlappen(dienst1, dienst2):
            medewerker = db.session.get(Medewerker, mw)
            waarschuwingen.append({
                "mw": mw, "datum": datum.isoformat(),
                "melding": f"Let op: de twee diensten van {medewerker.initialen} op "
                           f"{datum.strftime('%d-%m')} overlappen in tijd."})
    return waarschuwingen


def verwerk_rooster(wijzigingen: list[Wijziging], dag_wijzigingen=(), opslaan: bool = True,
                    ook_tonen=(), ook_dagen=()) -> dict:
    """Verwerk wijzigingen in het rooster: opslaan, of alleen een voorbeeld berekenen.

    opslaan=False: alles wordt uitgerekend (dienstnaam, standaardtijden, uren,
    weektotalen) en teruggegeven, maar daarna teruggedraaid. Zo ziet de planner
    direct het resultaat, terwijl er pas iets bewaard wordt bij 'Opslaan'.

    ook_tonen / ook_dagen: extra dagen waarvan de actuele stand mee terug moet
    (bijv. na 'ongedaan maken', zodat die cellen hun oude waarde weer tonen).
    Geeft {'bijgewerkt': {...}, 'dagopmerkingen': {...}, 'fouten': [...],
    'waarschuwingen': [...]} (waarschuwing: de twee diensten van een dag overlappen).
    """
    # Feestdagen van de betrokken jaren vooraf aanmaken. Dat moet vóór de wijzigingen,
    # want het aanmaken slaat direct op (en een voorbeeld mag niets opslaan).
    jaren = {w.datum.year for w in wijzigingen} | {d.year for d, _ in dag_wijzigingen} \
        | {d.year for _, d in ook_tonen} | {d.year for d in ook_dagen}
    for jaar in jaren:
        for j in (jaar - 1, jaar, jaar + 1):  # een week kan over de jaargrens lopen
            zorg_voor_jaar(j)

    try:
        geraakt, fouten = _pas_cellen_toe(wijzigingen)
        for datum, tekst in dag_wijzigingen:
            pas_dagopmerking_toe(datum, tekst)
        if wijzigingen or dag_wijzigingen:
            markeer_bijgewerkt()
        db.session.flush()

        # Antwoord opbouwen vóór opslaan/terugdraaien (dan zijn de gegevens nog actueel)
        regels = kleurregels()
        bijgewerkt = {}
        for mw, datum in geraakt | set(ook_tonen):
            gegevens = dag_naar_dict(*diensten_van_dag(mw, datum), regels)
            gegevens["weektotaal"] = formatteer_uren(weektotaal(mw, datum))
            bijgewerkt[f"{mw}|{datum.isoformat()}"] = gegevens
        waarschuwingen = overlap_waarschuwingen(geraakt)
        dagen = sorted({d for d, _ in dag_wijzigingen} | set(ook_dagen))
        dagresultaat = {d.isoformat(): v for d, v in dagopmerkingen(dagen).items()} if dagen else {}

        if opslaan:
            db.session.commit()
        else:
            db.session.rollback()  # alleen een voorbeeld: niets bewaren
        log.debug("Rooster %s: %s celwijzigingen, %s dagopmerkingen, %s geraakt, %s fouten",
                  "opgeslagen" if opslaan else "voorbeeld", len(wijzigingen), len(dag_wijzigingen),
                  len(geraakt), len(fouten))
        for fout in fouten:
            log.debug("Celfout: medewerker %s, %s, %s: %s", fout["mw"], fout["datum"], fout["veld"],
                      fout["melding"])
    except VersieConflict:
        db.session.rollback()
        log.debug("Versieconflict bij %s wijzigingen (opslaan=%s)", len(wijzigingen), opslaan)
        raise
    except IntegrityError as fout:  # tegelijk door een ander aangemaakt
        db.session.rollback()
        raise VersieConflict("Iemand anders wijzigde tegelijk dezelfde dienst.") from fout
    return {"bijgewerkt": bijgewerkt, "dagopmerkingen": dagresultaat, "fouten": fouten,
            "waarschuwingen": waarschuwingen}


def wijzig_cellen(wijzigingen: list[Wijziging]) -> tuple[dict, list[dict]]:
    """Wijzig cellen en sla direct op. Geeft (bijgewerkte dagen, fouten)."""
    resultaat = verwerk_rooster(wijzigingen, opslaan=True)
    return resultaat["bijgewerkt"], resultaat["fouten"]


def kopieer_week(van_maandag: date, naar_maandag: date, medewerker_id: int | None = None) -> int:
    """Maak de doelweek gelijk aan de bronweek (alle medewerkers of één).

    Een gearchiveerde medewerker krijgt geen diensten op of na zijn archiefdatum.
    Geeft het aantal gewijzigde dagen terug.
    """
    verschuiving = naar_maandag - van_maandag
    if not verschuiving:
        return 0
    query = Medewerker.query
    if medewerker_id:
        query = query.filter_by(id=medewerker_id)
    medewerkers = query.all()
    bron = {
        (d.medewerker_id, d.datum, d.volgnummer): d for d in Dienst.query.filter(
            Dienst.datum >= van_maandag, Dienst.datum <= van_maandag + timedelta(days=6)).all()
    }
    context = UrenContext(naar_maandag, naar_maandag + timedelta(days=6))
    gewijzigd = 0
    for medewerker in medewerkers:
        for i in range(7):
            dag_bron = van_maandag + timedelta(days=i)
            dag_doel = dag_bron + verschuiving
            if not medewerker.is_zichtbaar_op(dag_doel):
                continue  # gearchiveerd: niet meer inplannen
            dag_gewijzigd = False
            for volgnummer in range(1, MAX_DIENSTEN_PER_DAG + 1):  # beide diensten van de dag
                origineel = bron.get((medewerker.id, dag_bron, volgnummer))
                doel = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=dag_doel,
                                              volgnummer=volgnummer).first()
                if origineel is None and doel is None:
                    continue
                if doel is None:
                    doel = Dienst(medewerker_id=medewerker.id, datum=dag_doel, volgnummer=volgnummer,
                                  versie=0)
                    db.session.add(doel)
                for kolom, leeg in LEGE_DIENST.items():
                    setattr(doel, kolom, getattr(origineel, kolom) if origineel else leeg)
                doel.uren_berekend = uren_voor(doel, context)
                doel.versie = (doel.versie or 0) + 1
                if doel.is_leeg and not doel.google_event_id:
                    if doel in db.session.new:
                        db.session.expunge(doel)
                    else:
                        db.session.delete(doel)
                dag_gewijzigd = True
            if dag_gewijzigd:
                sync_planning.plan_dag(medewerker, dag_doel, commit=False)
                gewijzigd += 1

    naar_jaar, naar_week, _ = naar_maandag.isocalendar()
    van_jaar, van_week, _ = van_maandag.isocalendar()
    logboek.log("Week gekopieerd",
                f"W{van_week} {van_jaar} -> W{naar_week} {naar_jaar}, {gewijzigd} dagen",
                datum=naar_maandag,
                medewerker=medewerkers[0].naam if medewerker_id and medewerkers else "alle")
    markeer_bijgewerkt()
    db.session.commit()
    return gewijzigd


def komende_diensten(medewerker: Medewerker, weken: int = 8) -> list[Dienst]:
    """Diensten van vandaag t/m `weken` weken vooruit (voor 'Mijn rooster')."""
    vandaag = klok.vandaag()
    return (
        Dienst.query.filter(Dienst.medewerker_id == medewerker.id, Dienst.datum >= vandaag,
                            Dienst.datum < vandaag + timedelta(weeks=weken))
        .order_by(Dienst.datum, Dienst.volgnummer).all()
    )
