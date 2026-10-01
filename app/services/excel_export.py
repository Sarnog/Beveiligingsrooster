"""Het rooster exporteren naar MS Excel (.xlsx), in de opbouw van het oude Excel-rooster.

Zo kan het bestand weer ingelezen worden met Beheer → Excel import/export (zie de docstring
van excel_import.py). Bladen:
- W1..W53:      één blad per ISO-week, zoals het weekrooster: per dag drie kolommen
                (D, G, J, M, P, S, V), per medewerker vier regels (opmerking, opmerkingtijden,
                dienstnaam, begin/eind/uren), contracturen en weektotaal in Z, het code-raster
                in AB..AI. De tweede dienst van een dag staat rechts, vanaf AK ('2e dienst').
                Verborgen vanaf BH: de rekenhulp voor de uren (per dag 7 kolommen).
- Lijsten:      medewerkers met contracturen, dienstcodes, en de instellingen voor de uren:
                N2/N3 toeslag za/zo (zoals het oude bestand), N4 feestdag, N5 opmerkingtijden
                meetellen, N6 pauzeaftrek aan, N9:O13 de pauzestaffel.
- Feestdagen:   de feestdagen van het jaar (voor de feestdagtoeslag).
- Urenoverzicht zoals /overzicht/uren, Vakanties en Kalender (E2 = het jaar).
- Rekenhulp:    (verborgen) correcties voor de afronding, zie correcties().

Het bestand werkt in MS Excel zoals de app, zonder macro's (sinds 1.6.0). Formules:
- uren per dienst: minuten = MOD(eind - begin) in hele minuten, pauze uit de staffel (LOOKUP),
  × de toeslagfactor van de dag (za/zo, feestdag: de hoogste), afgerond op kwartieren met
  bankiersafronding (precies een half kwartier naar even), plus een correctie uit Rekenhulp
  voor de gevallen waarin de VBA door kommagetallen anders afrondt (zie urenberekening.py);
  bij dienst 1 komen de opmerkingtijden erbij als Lijsten!N5 = 1;
- weektotaal (Z) = SUM van de urencellen van dienst 1 en dienst 2; urenoverzicht verwijst naar Z;
- dienstnaam en standaardtijden zoeken de code uit het code-raster op in Lijsten, als de dienst
  de standaard van zijn code volgt (of de dag leeg is); anders zijn het vaste waarden;
- werkdagen per vakantie = NETWORKDAYS, zoals in het oude bestand.
Zelf ingevulde uren blijven een vaste waarde (rood, met een opmerking), net als in de app.
Datums in rij 2 zijn waarden (geen keten naar het vorige blad): zo klopt ook een losse week.

Wat NIET terugkomt bij een import: kleuren van dienstcodes en kleurregels (de import gebruikt
de kleuren uit het voorbeeldpakket of grijs), e-mailadressen, archiefdatums en agenda-
koppelingen, feestdagen en uitgezette feestdagen, de pauzestaffel en handmatig gewiste
automatische dagopmerkingen. Een periode moet binnen één ISO-jaar vallen: dan blijft de
export herimporteerbaar (één blad per weeknummer).

Tekst uit de database die met = + - of @ begint, wordt als tekst weggeschreven (nooit als
formule); formules bouwt alleen de export zelf, met eigen celverwijzingen (_formule).
"""

import io
import logging
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from functools import lru_cache

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, GradientFill, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Dienst, Dienstcode, Medewerker, Vakantie
from . import instellingen
from .excel_import import CODE_KOLOMMEN, DAG_KOLOMMEN, TWEEDE_KOLOMMEN
from .feestdagen import feestdagen_in_periode
from .kalender import (
    DAGNAMEN_KORT,
    MAX_JAAR,
    MIN_JAAR,
    aantal_weken,
    dagen_van_week,
    eerste_en_laatste_dag_isojaar,
)
from .overzichten import uren_overzicht
from .tijden import is_cijfers, parse_datum
from .urenberekening import Staffel, uren_uit_minuten
from .weekrooster import dagopmerkingen, kleurregels, matrix_code, medewerkers_voor_periode

log = logging.getLogger(__name__)
FORMULE_TEKENS = ("=", "+", "-", "@")
DUN = Side(style="thin", color="BFBFBF")
RAND = Border(left=DUN, right=DUN, top=DUN, bottom=DUN)
VET = Font(bold=True)
KOP = PatternFill("solid", fgColor="D9E1F2")
WEEKEND = PatternFill("solid", fgColor="F2F2F2")
MIDDEN = Alignment(horizontal="center", vertical="center")
# Gecentreerd over de lege cellen ernaast, zonder samenvoegen (dat is in openpyxl erg traag)
OVER_DRIE = Alignment(horizontal="centerContinuous", vertical="center")
TIJD = {"number_format": "hh:mm", "border": RAND}
UREN = {"number_format": "0.00", "border": RAND}
# Zelf ingevulde uren: rood, net als in het rooster (met een opmerking in de cel)
HANDMATIG = {"number_format": "0.00", "border": RAND, "font": Font(color="C00000", bold=True)}


class ExportFout(ValueError):
    """Ongeldige keuze voor de export (soort, week, periode, jaar, medewerker)."""


SOORTEN = {
    "week": "Eén week",
    "periode": "Een vrije periode (binnen één jaar)",
    "jaar": "Een heel jaar",
    "persoon": "Het jaarrooster van één persoon",
}


@dataclass(frozen=True)
class ExportKeuze:
    """Wat er geëxporteerd wordt: altijd binnen één ISO-jaar (dan blijft het herimporteerbaar)."""

    soort: str
    jaar: int  # ISO-jaar
    van: date
    tot: date
    medewerker: Medewerker | None = None
    week: int | None = None

    @property
    def bestandsnaam(self) -> str:
        """Bijv. rooster-2026.xlsx, rooster-2026-W10.xlsx, rooster-20260302-20260308-ma.xlsx."""
        if self.soort == "week":
            naam = f"rooster-{self.jaar}-W{self.week:02d}"
        elif self.soort == "periode":
            naam = f"rooster-{self.van:%Y%m%d}-{self.tot:%Y%m%d}"
        else:
            naam = f"rooster-{self.jaar}"
        if self.medewerker is not None:
            naam += f"-{self.medewerker.initialen.lower()}"
        return naam + ".xlsx"


def _geheel(tekst, omschrijving: str) -> int:
    tekst = (tekst or "").strip()
    if not is_cijfers(tekst) or len(tekst) > 6:
        raise ExportFout(f"Vul een geldig {omschrijving} in.")
    return int(tekst)


def _jaar(tekst) -> int:
    jaar = _geheel(tekst, "jaar")
    if not MIN_JAAR <= jaar <= MAX_JAAR:
        raise ExportFout(f"Kies een jaar tussen {MIN_JAAR} en {MAX_JAAR}.")
    return jaar


def keuze_uit(args) -> ExportKeuze:
    """De exportkeuze uit het formulier (een dict met tekst), volledig gecontroleerd (ExportFout).

    soort: week (jaar + week), periode (van + tot), jaar, persoon (jaar + medewerker, verplicht).
    Bij week, periode en jaar mag optioneel één medewerker gekozen worden.
    """
    soort = (args.get("soort") or "").strip()
    if soort not in SOORTEN:
        raise ExportFout("Kies wat je wilt exporteren: een week, een periode, een jaar of één persoon.")
    medewerker = None
    medewerker_tekst = (args.get("medewerker") or "").strip()
    if medewerker_tekst:
        medewerker = db.session.get(Medewerker, _geheel(medewerker_tekst, "medewerker")) \
            if len(medewerker_tekst) <= 9 else None
        if medewerker is None:
            raise ExportFout("Onbekende medewerker.")
    elif soort == "persoon":
        raise ExportFout("Kies de medewerker van wie je het jaarrooster wilt exporteren.")

    if soort == "week":
        jaar = _jaar(args.get("jaar"))
        week = _geheel(args.get("week"), "weeknummer")
        if not 1 <= week <= aantal_weken(jaar):
            raise ExportFout(f"{jaar} heeft de weken 1 t/m {aantal_weken(jaar)}; kies een week daarin.")
        dagen = dagen_van_week(jaar, week)
        return ExportKeuze(soort, jaar, dagen[0], dagen[-1], medewerker, week)
    if soort == "periode":
        van, tot = parse_datum(args.get("van") or ""), parse_datum(args.get("tot") or "")
        if van is None or tot is None:
            raise ExportFout("Vul een geldige periode in (van en t/m).")
        if tot < van:
            raise ExportFout("De einddatum van de periode ligt vóór de begindatum.")
        iso_jaar = van.isocalendar()[0]
        if not MIN_JAAR <= iso_jaar <= MAX_JAAR or not MIN_JAAR <= tot.isocalendar()[0] <= MAX_JAAR:
            raise ExportFout(f"Kies een periode tussen {MIN_JAAR} en {MAX_JAAR}.")
        if tot.isocalendar()[0] != iso_jaar:
            eerste, laatste = eerste_en_laatste_dag_isojaar(iso_jaar)
            raise ExportFout(
                f"De periode moet binnen één roosterjaar vallen ({iso_jaar}: {eerste:%d-%m-%Y} t/m "
                f"{laatste:%d-%m-%Y}, ISO-weken). Een export heeft één blad per weeknummer en is zo "
                "weer in te lezen; exporteer een langere periode per jaar.")
        return ExportKeuze(soort, iso_jaar, van, tot, medewerker)
    jaar = _jaar(args.get("jaar"))
    eerste, laatste = eerste_en_laatste_dag_isojaar(jaar)
    return ExportKeuze(soort, jaar, eerste, laatste, medewerker)


# ---------------------------------------------------------------------------
# Hulpjes voor cellen
# ---------------------------------------------------------------------------

# Opmaak per combinatie één keer opbouwen en daarna kopiëren: elke losse toekenning
# (font, fill, ...) kost in openpyxl een opzoeking in de stijllijsten van het werkboek.
# De cache hoort bij het werkboek (de stijlnummers verwijzen naar diens lijsten).


def _zet_als(blad, rij: int, kolom: int, waarde, stijl: dict | None = None) -> None:
    """Als _zet, maar een lege waarde slaan we over (geen lege, opgemaakte cel: scheelt tijd)."""
    if waarde is not None and waarde != "":
        _zet(blad, rij, kolom, waarde, stijl)


def _zet(blad, rij: int, kolom: int, waarde, stijl: dict | None = None):
    """Schrijf een waarde; tekst die als formule gelezen kan worden blijft tekst."""
    cel = blad.cell(rij, kolom)
    cel.value = waarde
    formule = isinstance(waarde, str) and waarde.startswith(FORMULE_TEKENS)
    if formule:
        cel.data_type = "s"  # openpyxl maakt anders een formule van '=...'
    if stijl or formule:
        cache = blad.parent.__dict__.setdefault("_rooster_stijlen", {})
        sleutel = (formule,) + tuple((k, id(v)) for k, v in (stijl or {}).items())
        if sleutel in cache:
            cel._style = copy(cache[sleutel][0])
        else:
            for naam, stijlwaarde in (stijl or {}).items():
                setattr(cel, naam, stijlwaarde)
            if formule:
                cel.quotePrefix = True  # Excel toont het als tekst
            # De stijlobjecten zelf ook bewaren: zo blijft hun id() uniek zolang de cache bestaat
            cache[sleutel] = (copy(cel._style), tuple((stijl or {}).values()))
    return cel


def _tijd(tekst: str | None) -> time | None:
    return time.fromisoformat(tekst) if tekst else None


class _Stijlen:
    """Opvulling en lettertype per dienstcode en kleurregel, één keer gemaakt (snelheid)."""

    def __init__(self) -> None:
        self.codes: dict[int, dict] = {}
        self.regels = {}
        for sleutel, regel in kleurregels().items():
            if regel.kleur_achtergrond2:
                kleuren = (_kleur(regel.kleur_achtergrond), _kleur(regel.kleur_achtergrond2))
                vulling = GradientFill(stop=kleuren)
            else:
                vulling = PatternFill("solid", fgColor=_kleur(regel.kleur_achtergrond))
            self.regels[sleutel] = {"fill": vulling, "font": Font(color=_kleur(regel.kleur_tekst))}

    def code(self, code: Dienstcode | None) -> dict:
        if code is None:
            return {}
        if code.id not in self.codes:
            self.codes[code.id] = {
                "fill": PatternFill("solid", fgColor=_kleur(code.kleur_achtergrond)),
                "font": Font(color=_kleur(code.kleur_tekst), bold=code.vet, italic=code.cursief),
            }
        return self.codes[code.id]

    def raster(self, dienst1: Dienst | None, dienst2: Dienst | None) -> dict:
        """Code-cel: kleur van de code; bij twee diensten links/rechts (verloop)."""
        if dienst2 is None:
            return self.code(dienst1.dienstcode if dienst1 else None)
        kleuren = [_kleur(d.dienstcode.kleur_achtergrond) if d is not None and d.dienstcode else "FFFFFF"
                   for d in (dienst1, dienst2)]
        return {"fill": GradientFill(stop=tuple(kleuren)), "font": VET}

    def opmerking(self, tekst: str) -> dict:
        return self.regels.get((tekst or "").strip().casefold(), {})


def _kleur(waarde: str | None) -> str:
    """'#AABBCC' -> 'AABBCC' (openpyxl wil geen '#')."""
    return (waarde or "#FFFFFF").lstrip("#").upper()[:6] or "FFFFFF"


# ---------------------------------------------------------------------------
# Rekenregels als Excel-formules (zie de docstring bovenaan)
# ---------------------------------------------------------------------------

# Lijsten: instellingenblok voor de uren (kolom M = omschrijving, N = waarde)
CEL_ZATERDAG, CEL_ZONDAG, CEL_FEESTDAG = "Lijsten!$N$2", "Lijsten!$N$3", "Lijsten!$N$4"
CEL_OPMERKINGTIJDEN, CEL_PAUZE_AAN = "Lijsten!$N$5", "Lijsten!$N$6"
PAUZE_EERSTE_RIJ = 9  # N9:N13 = grens ('meer dan ... uur'), O9:O13 = pauze eraf
CEL_CORRECTIES_GELDIG = "Rekenhulp!$D$1"
# Rekenhulp per dag (verborgen kolommen rechts van de tweede dienst), per dag 7 kolommen:
# X dienst 1, uren dienst 1, X opmerkingtijden, uren opmerkingtijden, X dienst 2, code 1, code 2
HULP_EERSTE = 60  # kolom BH
HULP_BREEDTE = 7
MINUTEN_PER_DAG = 1440
# Rekenhulp: sleutel = factor×1000×1440 + minuten; tekst = per begintijd één teken (correctie + 80)
NUL_TEKEN = 80  # 'P' = geen correctie
MAX_CORRECTIE = 40  # tekens 40..120: altijd gewone, leesbare tekens


def _hulpkolom(dag: int, nummer: int) -> int:
    return HULP_EERSTE + HULP_BREEDTE * dag + nummer


def _cel(rij: int, kolom: int, vast: bool = False) -> str:
    letter = get_column_letter(kolom)
    return f"${letter}${rij}" if vast else f"{letter}{rij}"


def _getal(waarde: float) -> str:
    """Getal in een formule (altijd met een punt, ook in een Nederlandse Excel)."""
    return repr(float(waarde)).removesuffix(".0")


class _Formules:
    """Bouwt de formules voor één export; de instellingen zitten in het blad Lijsten."""

    def __init__(self, staffel_regels: int, correcties: int) -> None:
        self.staffel_regels = staffel_regels
        self.correcties = correcties  # aantal regels in Rekenhulp (0 = geen correcties nodig)

    @staticmethod
    def minuten(begin: str, eind: str) -> str:
        """Gewerkte minuten, over middernacht (begin en eind afgerond op hele minuten)."""
        return f"MOD(ROUND({eind}*1440,0)-ROUND({begin}*1440,0),1440)"

    def pauze(self, minuten: str) -> str:
        """Pauze eraf: de hoogste grens die overschreden is (precies op de grens telt niet)."""
        if not self.staffel_regels:
            return "0"
        laatste = PAUZE_EERSTE_RIJ + self.staffel_regels - 1
        return (f"IF({CEL_PAUZE_AAN}=1,IFERROR(LOOKUP({minuten}/60-1E-9,Lijsten!$N${PAUZE_EERSTE_RIJ}:"
                f"$N${laatste},Lijsten!$O${PAUZE_EERSTE_RIJ}:$O${laatste}),0),0)")

    def kwartieren_ruw(self, begin: str, eind: str, factor: str) -> str:
        """X = (uren - pauze) * factor * 4, of "" zonder begin- of eindtijd."""
        minuten = self.minuten(begin, eind)
        return f'IF(COUNT({begin},{eind})<2,"",({minuten}/60-{self.pauze(minuten)})*{factor}*4)'

    def uren(self, x: str, begin: str, eind: str, factor: str) -> str:
        """Afronden op kwartieren als de app: precies een half kwartier naar even (bankiers),
        plus de correctie uit Rekenhulp waar de VBA door kommagetallen anders afrondt."""
        afgerond = f"IF(MOD(ROUND({x}*2,6),2)=1,2*ROUND({x}/2,0),ROUND({x},0))"
        if self.correcties:
            sleutel = f"ROUND({factor}*1000,0)*1440+{self.minuten(begin, eind)}"
            laatste = self.correcties + 1
            afgerond += (f"+IF({CEL_CORRECTIES_GELDIG},IFERROR(CODE(MID(VLOOKUP({sleutel},Rekenhulp!$A$2:"
                         f"$B${laatste},2,FALSE),MOD(ROUND({begin}*1440,0),1440)+1,1))-{NUL_TEKEN},0),0)")
        return f'IF({x}="","",({afgerond})/4)'

    @staticmethod
    def dagtotaal(uren1: str, uren_opm: str) -> str:
        """Uren van dienst 1: de tijdenregel plus (als dat aan staat) de opmerkingtijden."""
        return (f'IF(AND({uren1}="",OR({CEL_OPMERKINGTIJDEN}<>1,{uren_opm}="")),"",'
                f"N({uren1})+IF({CEL_OPMERKINGTIJDEN}=1,N({uren_opm}),0))")

    @staticmethod
    def factor(datum: str, feestdagen: int) -> str:
        """Toeslagfactor van een dag: za/zo, en de hoogste factor bij weekend + feestdag."""
        weekend = f"IF(WEEKDAY({datum})=7,{CEL_ZATERDAG},IF(WEEKDAY({datum})=1,{CEL_ZONDAG},1))"
        if not feestdagen:
            return weekend
        return (f'MAX({weekend},IF(AND({CEL_FEESTDAG}<>"",COUNTIF(Feestdagen!$A$2:$A${feestdagen + 1},'
                f"{datum})>0),{CEL_FEESTDAG},0))")

    @staticmethod
    def code(raster: str, volgnummer: int) -> str:
        """De code van dienst 1 of 2 uit de code-cel ('4', of '4/7' bij twee diensten)."""
        if volgnummer == 1:
            return f'IF(ISNUMBER({raster}),{raster},IFERROR(VALUE(LEFT({raster},FIND("/",{raster})-1)),""))'
        return f'IFERROR(VALUE(MID({raster},FIND("/",{raster})+1,9)),"")'

    @staticmethod
    def opzoeken(code: str, kolom: int, codes: int) -> str:
        """Omschrijving (kolom 2) of standaardtijd (6 = van, 7 = tot) van een code uit Lijsten."""
        return f'IFERROR(VLOOKUP({code},Lijsten!$F$2:$L${codes + 1},{kolom},FALSE),"")'


@lru_cache(maxsize=32)
def correcties(factor: float, staffel: Staffel) -> tuple[tuple[int, str], ...]:
    """Waar bereken_uren anders uitkomt dan exact rekenen: ((sleutel, tekst), ...).

    De app rekent als de VBA met kommagetallen (zie urenberekening.py): bij precies een half
    kwartier of precies een pauzegrens beslist dan het kommagetal, en dat hangt af van de
    begintijd. Excel rondt met 15 cijfers af en ziet dat verschil niet; daarom staan alle
    afwijkende gevallen (voor deze factor en pauzestaffel) in het blad Rekenhulp.
    Per aantal gewerkte minuten één regel: sleutel = factor×1000×1440 + minuten, tekst = per
    begintijd (0..1439 minuten) één teken: chr(NUL_TEKEN + correctie in kwartieren).
    Alleen minuten die exact op een half kwartier of een grens uitkomen kunnen afwijken.
    """
    exacte_factor = Fraction(str(factor))
    grenzen = {Fraction(str(g)) * 60 for g, _ in staffel}
    resultaat = []
    for minuten in range(MINUTEN_PER_DAG):
        # Wat de formules zonder correctie geven: exact rekenen, half kwartier naar even
        x = (Fraction(minuten, 60) - _aftrek_exact(minuten, staffel)) * exacte_factor * 4
        half_kwartier = (x * 2).denominator == 1 and (x * 2).numerator % 2 == 1
        if not half_kwartier and minuten not in grenzen:
            continue  # kommagetallen maken hier niets uit
        exact = round(x)  # round() op een Fraction: exact, half naar even
        verschillen = [round(uren_uit_minuten(begin, (begin + minuten) % MINUTEN_PER_DAG, factor,
                                              staffel) * 4) - exact for begin in range(MINUTEN_PER_DAG)]
        if any(abs(v) > MAX_CORRECTIE for v in verschillen):
            # Kan alleen bij een extreme pauze × factor; dan liever geen correctie dan een fout teken
            log.warning("Excel-export: correctie buiten bereik (factor %s, %s minuten)", factor, minuten)
        elif any(verschillen):
            resultaat.append((round(factor * 1000) * MINUTEN_PER_DAG + minuten,
                              "".join(chr(NUL_TEKEN + v) for v in verschillen)))
    return tuple(resultaat)


def _aftrek_exact(minuten: int, staffel: Staffel) -> Fraction:
    """De pauze zoals de formule hem bepaalt: met hele minuten, precies op de grens telt niet."""
    aftrek = Fraction(0)
    for grens, regel in staffel:
        if minuten > Fraction(str(grens)) * 60:
            aftrek = Fraction(str(regel))
    return aftrek


# ---------------------------------------------------------------------------
# De export
# ---------------------------------------------------------------------------

def maak_export(keuze: ExportKeuze) -> bytes:
    """Bouw het .xlsx-bestand en geef de inhoud (bytes)."""
    jaar, van, tot, medewerker = keuze.jaar, keuze.van, keuze.tot, keuze.medewerker
    eerste, laatste = eerste_en_laatste_dag_isojaar(jaar)
    medewerkers = [medewerker] if medewerker is not None else medewerkers_voor_periode(van, tot)
    ids = [m.id for m in medewerkers]
    diensten = (Dienst.query.options(joinedload(Dienst.dienstcode))
                .filter(Dienst.datum >= van, Dienst.datum <= tot, Dienst.medewerker_id.in_(ids)).all())
    per_dag: dict[tuple[int, date], dict[int, Dienst]] = {}
    for dienst in diensten:
        if not dienst.is_leeg or dienst.volgnummer == 1:
            per_dag.setdefault((dienst.medewerker_id, dienst.datum), {})[dienst.volgnummer] = dienst
    dagen_jaar = [eerste + timedelta(days=i) for i in range((laatste - eerste).days + 1)]
    feestdagen = feestdagen_in_periode(eerste, laatste)
    opmerkingen = dagopmerkingen(dagen_jaar, feestdagen)
    codes = Dienstcode.query.order_by(Dienstcode.nummer).all()
    toeslagen = instellingen.toeslagen()
    pauze = instellingen.pauze_instelling()
    staffel = tuple(pauze["regels"]) if pauze["aan"] else ()
    factoren = sorted({1.0, toeslagen["factor_zaterdag"], toeslagen["factor_zondag"]}
                      | ({toeslagen["factor_feestdag"]} if toeslagen["factor_feestdag"] else set()))
    tabel = sorted({c for f in factoren for c in correcties(f, staffel)})
    formules = _Formules(len(pauze["regels"]), len(tabel))
    stijlen = _Stijlen()

    boek = Workbook()
    boek.remove(boek.active)
    weken = sorted({d.isocalendar()[1] for d in dagen_jaar if van <= d <= tot})
    context = _WeekContext(jaar, van, tot, medewerkers, per_dag, opmerkingen, stijlen, formules,
                           len(codes), len(feestdagen))
    for week in weken:
        _weekblad(boek.create_sheet(f"W{week}"), week, context)
    _lijsten(boek.create_sheet("Lijsten"), jaar, medewerkers, codes, toeslagen, pauze, stijlen)
    _feestdagen(boek.create_sheet("Feestdagen"), feestdagen)
    _urenoverzicht(boek.create_sheet("Urenoverzicht"), jaar, medewerker, medewerkers, set(weken))
    _vakanties(boek.create_sheet("Vakanties"), van, tot)
    kalender = boek.create_sheet("Kalender")
    _zet(kalender, 1, 5, "Jaar", {"font": VET})
    _zet(kalender, 2, 5, jaar)
    _zet(kalender, 1, 1, f"Rooster {jaar}: {van:%d-%m-%Y} t/m {tot:%d-%m-%Y}", {"font": VET})
    _rekenhulp(boek.create_sheet("Rekenhulp"), tabel, pauze)
    boek.calculation.fullCalcOnLoad = True  # Excel rekent alles uit bij het openen
    uitvoer = io.BytesIO()
    boek.save(uitvoer)
    log.debug("Excel-export: %s weken, %s medewerkers, %s diensten, %s correcties", len(weken),
              len(medewerkers), len(diensten), len(tabel))
    return uitvoer.getvalue()


@dataclass
class _WeekContext:
    jaar: int
    van: date
    tot: date
    medewerkers: list[Medewerker]
    per_dag: dict
    opmerkingen: dict
    stijlen: "_Stijlen"
    formules: _Formules
    codes: int  # aantal dienstcodes in Lijsten
    feestdagen: int  # aantal regels in het blad Feestdagen


def _weekblad(blad, week: int, c: _WeekContext) -> None:
    maandag = date.fromisocalendar(c.jaar, week, 1)
    dagen = [maandag + timedelta(days=i) for i in range(7)]
    _zet(blad, 1, 2, f"Week {week} ({c.jaar})", {"font": Font(bold=True, size=13)})
    _zet(blad, 2, 2, "Naam", {"font": VET})
    _zet(blad, 2, 26, "Uren", {"font": VET})
    _zet(blad, 1, 28, "Code-raster", {"font": VET})
    _zet(blad, 3, TWEEDE_KOLOMMEN[0], "2e dienst van de dag (bij twee diensten)", {"font": VET})
    _zet(blad, 1, HULP_EERSTE, "Rekenhulp voor de uren (niet wijzigen); rij 2 = toeslagfactor", {"font": VET})
    for i, dag in enumerate(dagen):
        weekend = {"fill": WEEKEND} if dag.weekday() >= 5 else {"fill": KOP}
        for kolom in (DAG_KOLOMMEN[i], TWEEDE_KOLOMMEN[i]):
            _zet(blad, 1, kolom, DAGNAMEN_KORT[i], {"font": VET, "alignment": OVER_DRIE, **weekend})
            for k in (kolom + 1, kolom + 2):
                _zet(blad, 1, k, None, weekend)
                _zet(blad, 2, k, None, weekend)
            _zet(blad, 2, kolom, datetime.combine(dag, time()),
                 {"number_format": "dd-mm-yy", "font": VET, "alignment": OVER_DRIE, **weekend})
        _zet(blad, 2, CODE_KOLOMMEN[i], DAGNAMEN_KORT[i].upper(), {"font": VET, "alignment": MIDDEN})
        if c.van <= dag <= c.tot:
            opm = c.opmerkingen.get(dag, {}).get("tekst", "")
            _zet(blad, 3, DAG_KOLOMMEN[i], opm or None, {"alignment": OVER_DRIE})
            datum = _cel(2, DAG_KOLOMMEN[i], True)
            _formule(blad, 2, _hulpkolom(i, 0), c.formules.factor(datum, c.feestdagen))

    for n, medewerker in enumerate(c.medewerkers):
        basis = 4 + 4 * n
        _zet(blad, basis, 2, medewerker.naam, {"font": VET})
        _zet(blad, 6 + 2 * n, 28, medewerker.initialen, {"font": VET})
        _zet(blad, basis, 26, medewerker.contracturen_voor(c.jaar))
        urencellen = []
        for i, dag in enumerate(dagen):
            urencellen += [_cel(basis + 3, DAG_KOLOMMEN[i] + 2), _cel(basis + 3, TWEEDE_KOLOMMEN[i] + 2)]
            if c.van <= dag <= c.tot:
                _dag(blad, basis, 6 + 2 * n, i, c.per_dag.get((medewerker.id, dag), {}), c)
        # Weektotaal: alle urencellen van dienst 1 en dienst 2 (lege cellen tellen niet)
        _formule(blad, basis + 2, 26, f"SUM({','.join(urencellen)})", {"font": VET, "number_format": "0.00"})
    _opmaak_weekblad(blad)


def _dag(blad, basis: int, rasterrij: int, i: int, per_vn: dict, c: _WeekContext) -> None:
    """Eén dag van één medewerker: opmerking, code-raster, dienst 1 en dienst 2 (met formules)."""
    dienst1, dienst2 = per_vn.get(1), per_vn.get(2)
    if dienst1 is not None and dienst1.is_leeg and dienst2 is None:
        dienst1 = None
    kolom, k2 = DAG_KOLOMMEN[i], TWEEDE_KOLOMMEN[i]
    if dienst1 is not None or dienst2 is not None:
        code = matrix_code(dienst1, dienst2)
        if code:
            _zet(blad, rasterrij, CODE_KOLOMMEN[i], int(code) if code.isdigit() else code,
                 {"alignment": MIDDEN, **c.stijlen.raster(dienst1, dienst2)})
    if dienst1 is not None:
        opmerking = dienst1.opmerking_tekst
        _zet_als(blad, basis, kolom, opmerking, {**c.stijlen.opmerking(opmerking), "border": RAND})
        _zet_als(blad, basis + 1, kolom, _tijd(dienst1.opmerking_begin), TIJD)
        _zet_als(blad, basis + 1, kolom + 1, _tijd(dienst1.opmerking_eind), TIJD)

    f = c.formules
    rij = basis + 3
    factor = _cel(2, _hulpkolom(i, 0), True)
    raster = _cel(rasterrij, CODE_KOLOMMEN[i], True)
    code1, code2 = _cel(rij, _hulpkolom(i, 5)), _cel(rij, _hulpkolom(i, 6))
    _formule(blad, rij, _hulpkolom(i, 5), f.code(raster, 1))
    _formule(blad, rij, _hulpkolom(i, 6), f.code(raster, 2))
    # Rekenhulp: X en uren van dienst 1, de opmerkingtijden en dienst 2
    for nummer, (b, e) in ((0, (_cel(rij, kolom), _cel(rij, kolom + 1))),
                           (2, (_cel(basis + 1, kolom), _cel(basis + 1, kolom + 1))),
                           (4, (_cel(rij, k2), _cel(rij, k2 + 1)))):
        x = f.kwartieren_ruw(b, e, factor)
        _formule(blad, rij, _hulpkolom(i, nummer), x)
        if nummer < 4:
            _formule(blad, rij, _hulpkolom(i, nummer + 1),
                     f.uren(_cel(rij, _hulpkolom(i, nummer)), b, e, factor))
    uren1 = f.dagtotaal(_cel(rij, _hulpkolom(i, 1)), _cel(rij, _hulpkolom(i, 3)))
    uren2 = f.uren(_cel(rij, _hulpkolom(i, 4)), _cel(rij, k2), _cel(rij, k2 + 1), factor)
    _dienst(blad, basis, kolom, dienst1, code1, uren1, c)
    _dienst(blad, basis, k2, dienst2, code2, uren2, c)


def _volgt_standaard(dienst: Dienst) -> bool:
    """Dienst met een code, zonder eigen naam en met de standaardtijden van die code."""
    code = dienst.dienstcode
    return (code is not None and not dienst.dienstnaam_override
            and (dienst.begin, dienst.eind) == (code.std_begin, code.std_eind))


def _dienst(blad, basis: int, kolom: int, dienst: Dienst | None, code: str, uren: str,
            c: _WeekContext) -> None:
    """Dienstnaam (regel c) en begin/eind/uren (regel d) van één dienst.

    Volgt de dienst de standaard van zijn code (of is er nog geen dienst), dan zoeken
    formules naam en tijden op in Lijsten: een andere code in het code-raster werkt dan door.
    Een afwijkende tijd, een vrije dienstnaam of een aanvulling achter de naam blijft een waarde.
    Zelf ingevulde uren blijven een vaste waarde (rood, met een opmerking), net als in de app.
    """
    stijl = c.stijlen.code(dienst.dienstcode if dienst is not None else None)
    naam = {**stijl, "alignment": OVER_DRIE, "border": RAND}
    if dienst is None or _volgt_standaard(dienst):
        _formule(blad, basis + 2, kolom, c.formules.opzoeken(code, 2, c.codes), naam)
        _formule(blad, basis + 3, kolom, c.formules.opzoeken(code, 6, c.codes), TIJD)
        _formule(blad, basis + 3, kolom + 1, c.formules.opzoeken(code, 7, c.codes), TIJD)
    else:
        _zet(blad, basis + 2, kolom, dienst.dienstnaam or None, naam)
        _zet_als(blad, basis + 3, kolom, _tijd(dienst.begin), TIJD)
        _zet_als(blad, basis + 3, kolom + 1, _tijd(dienst.eind), TIJD)
    if dienst is not None:
        for k in (kolom + 1, kolom + 2):  # kleur over de hele breedte van de dag
            _zet(blad, basis + 2, k, None, naam)
    if dienst is not None and dienst.uren_handmatig is not None:
        cel = _zet(blad, basis + 3, kolom + 2, dienst.uren_handmatig, HANDMATIG)
        cel.comment = Comment("Zelf ingevulde uren (vaste waarde, geen formule)", "Beveiligingsrooster")
    else:
        _formule(blad, basis + 3, kolom + 2, uren, UREN)


def _formule(blad, rij: int, kolom: int, formule: str, stijl: dict | None = None):
    """Een formule die de export zelf opbouwt (alleen eigen celverwijzingen, nooit tekst uit de
    database). _zet() maakt van tekst die met '=' begint juist géén formule."""
    cel = blad.cell(rij, kolom)
    cel.value = "=" + formule
    if stijl:
        cache = blad.parent.__dict__.setdefault("_rooster_stijlen", {})
        sleutel = ("f",) + tuple((k, id(v)) for k, v in stijl.items())
        if sleutel in cache:
            cel._style = copy(cache[sleutel][0])
        else:
            for naam, waarde in stijl.items():
                setattr(cel, naam, waarde)
            cache[sleutel] = (copy(cel._style), tuple(stijl.values()))
    return cel


def _opmaak_weekblad(blad) -> None:
    blad.column_dimensions["A"].width = 2
    blad.column_dimensions["B"].width = 22
    for kolom in DAG_KOLOMMEN + TWEEDE_KOLOMMEN:
        for k in range(3):
            blad.column_dimensions[get_column_letter(kolom + k)].width = 7
    blad.column_dimensions["Z"].width = 9
    # De rekenhulp verbergen (uitklapbaar via de groepering)
    blad.column_dimensions.group(get_column_letter(HULP_EERSTE),
                                 get_column_letter(_hulpkolom(6, HULP_BREEDTE - 1)), hidden=True)
    blad.freeze_panes = "C4"
    blad.sheet_view.zoomScale = 90


def _lijsten(blad, jaar: int, medewerkers: list[Medewerker], codes: list[Dienstcode], toeslagen: dict,
             pauze: dict, stijlen: "_Stijlen") -> None:
    for kolom, kop in ((2, "Initialen"), (3, "Personeel"), (4, f"Contract {jaar}"), (6, "Dienst"),
                       (7, "Omschrijving"), (8, "Van"), (9, "Tot"), (10, "Uren"), (13, "Instelling"),
                       (14, "Waarde")):
        _zet(blad, 1, kolom, kop, {"font": VET, "fill": KOP})
    for rij, medewerker in enumerate(medewerkers, start=2):
        _zet(blad, rij, 2, medewerker.initialen)
        _zet(blad, rij, 3, medewerker.naam)
        _zet(blad, rij, 4, medewerker.contracturen_voor(jaar))
    for rij, code in enumerate(codes, start=2):
        _zet(blad, rij, 6, code.nummer)
        _zet(blad, rij, 7, code.omschrijving, stijlen.code(code))
        _zet(blad, rij, 8, _tijd(code.std_begin), {"number_format": "hh:mm"})
        _zet(blad, rij, 9, _tijd(code.std_eind), {"number_format": "hh:mm"})
        _zet(blad, rij, 10, code.std_uren)
        # Hulpkolommen K/L: een code zonder standaardtijd geeft "" (anders toont Excel 00:00)
        _formule(blad, rij, 11, f'IF(H{rij}="","",H{rij})', {"number_format": "hh:mm"})
        _formule(blad, rij, 12, f'IF(I{rij}="","",I{rij})', {"number_format": "hh:mm"})
    blad.column_dimensions.group("K", "L", hidden=True)
    instellingen_blok = [
        (2, "Toeslag zaterdag", toeslagen["factor_zaterdag"]),
        (3, "Toeslag zondag", toeslagen["factor_zondag"]),
        (4, "Toeslag feestdag (leeg = geen)", toeslagen["factor_feestdag"]),
        (5, "Opmerkingtijden meetellen (1 = ja)", 1 if instellingen.lees_bool("opmerkingtijden_meetellen")
         else 0),
        (6, "Pauzeaftrek aan (1 = ja)", 1 if pauze["aan"] else 0),
    ]
    for rij, omschrijving, waarde in instellingen_blok:
        _zet(blad, rij, 13, omschrijving)
        _zet(blad, rij, 14, waarde)
    _zet(blad, PAUZE_EERSTE_RIJ - 1, 13, "Pauze per dienst", {"font": VET})
    _zet(blad, PAUZE_EERSTE_RIJ - 1, 14, "meer dan (uur)", {"font": VET})
    _zet(blad, PAUZE_EERSTE_RIJ - 1, 15, "eraf (uur)", {"font": VET})
    for rij, (grens, aftrek) in enumerate(pauze["regels"], start=PAUZE_EERSTE_RIJ):
        _zet(blad, rij, 13, f"regel {rij - PAUZE_EERSTE_RIJ + 1}")
        _zet(blad, rij, 14, grens)
        _zet(blad, rij, 15, aftrek)
    _zet(blad, PAUZE_EERSTE_RIJ + 6, 13, "De uren in de weekbladen rekenen met deze instellingen, net als de "
         "app. Wijzig ze bij voorkeur in de app (Beheer → Instellingen) en exporteer opnieuw.")
    for kolom, breedte in (("B", 10), ("C", 26), ("G", 22), ("M", 34)):
        blad.column_dimensions[kolom].width = breedte


def _feestdagen(blad, feestdagen: dict[date, str]) -> None:
    """Feestdagen (en eigen roostervrije dagen) van het jaar, voor de feestdagtoeslag."""
    for kolom, kop in enumerate(("Datum", "Feestdag"), start=1):
        _zet(blad, 1, kolom, kop, {"font": VET, "fill": KOP})
    for rij, (dag, naam) in enumerate(sorted(feestdagen.items()), start=2):
        _zet(blad, rij, 1, datetime.combine(dag, time()), {"number_format": "dd-mm-yyyy"})
        _zet(blad, rij, 2, naam)
    blad.column_dimensions["A"].width = 12
    blad.column_dimensions["B"].width = 30


def _urenoverzicht(blad, jaar: int, medewerker: Medewerker | None, op_weekbladen: list[Medewerker],
                   weekbladen: set[int]) -> None:
    """Weektotalen per medewerker: formules naar kolom Z van de weekbladen in dit bestand.

    Weken (of medewerkers) die niet in het bestand staan, krijgen de waarde uit de app.
    """
    weken = list(range(1, aantal_weken(jaar) + 1))
    koppen = ["Naam", "Initialen"] + [f"W{w}" for w in weken] + ["Totaal", "Contracturen", "Verschil"]
    for kolom, kop in enumerate(koppen, start=1):
        _zet(blad, 1, kolom, kop, {"font": VET, "fill": KOP})
    plek = {m.id: n for n, m in enumerate(op_weekbladen)}
    rijen = [r for r in uren_overzicht(jaar) if medewerker is None or r.medewerker.id == medewerker.id]
    getal = {"number_format": "0.00;-0.00;;@"}  # 0 als leeg tonen (een week zonder diensten)
    eerste, laatste = get_column_letter(3), get_column_letter(len(weken) + 2)
    for rij, r in enumerate(rijen, start=2):
        _zet(blad, rij, 1, r.medewerker.naam)
        _zet(blad, rij, 2, r.medewerker.initialen)
        for kolom, week in enumerate(weken, start=3):
            if week in weekbladen and r.medewerker.id in plek:
                _formule(blad, rij, kolom, f"'W{week}'!$Z${6 + 4 * plek[r.medewerker.id]}", getal)
            else:
                _zet(blad, rij, kolom, r.per_week.get(week), getal)
        totaal = _cel(rij, len(weken) + 3)
        contract = _cel(rij, len(weken) + 4)
        _formule(blad, rij, len(weken) + 3, f"SUM({eerste}{rij}:{laatste}{rij})",
                 {"number_format": "0.00", "font": VET})
        _zet(blad, rij, len(weken) + 4, r.contracturen, {"number_format": "0.00"})
        _formule(blad, rij, len(weken) + 5, f'IF({contract}="","",{totaal}-{contract})',
                 {"number_format": "0.00"})
    blad.column_dimensions["A"].width = 24
    blad.freeze_panes = "C2"


def _vakanties(blad, van: date, tot: date) -> None:
    for kolom, kop in enumerate(("Vakantie", "Datum van", "Datum tot", "Werkdagen"), start=1):
        _zet(blad, 1, kolom, kop, {"font": VET, "fill": KOP})
    vakanties = (Vakantie.query.filter(Vakantie.datum_tot >= van, Vakantie.datum_van <= tot)
                 .order_by(Vakantie.datum_van).all())
    for rij, vakantie in enumerate(vakanties, start=2):
        _zet(blad, rij, 1, vakantie.naam)
        _zet(blad, rij, 2, datetime.combine(vakantie.datum_van, time()), {"number_format": "dd-mm-yyyy"})
        _zet(blad, rij, 3, datetime.combine(vakantie.datum_tot, time()), {"number_format": "dd-mm-yyyy"})
        _formule(blad, rij, 4, f"NETWORKDAYS(B{rij},C{rij})")  # zoals in het oude Excel-bestand
    if vakanties:
        rij = len(vakanties) + 2
        _zet(blad, rij, 3, "Totaal", {"font": VET})
        _formule(blad, rij, 4, f"SUM(D2:D{rij - 1})", {"font": VET})
    blad.column_dimensions["A"].width = 24
    for kolom in ("B", "C"):
        blad.column_dimensions[kolom].width = 12


def _rekenhulp(blad, tabel, pauze: dict) -> None:
    """Correcties voor de afronding (zie correcties()) en de controle of ze nog gelden."""
    _zet(blad, 1, 1, "Sleutel", {"font": VET})
    _zet(blad, 1, 2, "Correctie per begintijd", {"font": VET})
    _zet(blad, 1, 3, "Correcties gelden:", {"font": VET})
    # Alleen zolang de pauzeregels in Lijsten nog die van de export zijn
    voorwaarden = [f"{CEL_PAUZE_AAN}={1 if pauze['aan'] else 0}"]
    if pauze["aan"]:
        for rij, (grens, aftrek) in enumerate(pauze["regels"], start=PAUZE_EERSTE_RIJ):
            voorwaarden += [f"Lijsten!$N${rij}={_getal(grens)}", f"Lijsten!$O${rij}={_getal(aftrek)}"]
    _formule(blad, 1, 4, f"AND({','.join(voorwaarden)})")
    _zet(blad, 2, 4, "Waarom dit blad? De app rekent de uren precies als de oude Excel-macro, met "
         "kommagetallen. Komt een dienst precies op een half kwartier of een pauzegrens uit, dan "
         "beslist het kommagetal, en dat hangt af van de begintijd; Excel-formules zien dat verschil "
         "niet. Per toeslagfactor en aantal gewerkte minuten (sleutel = factor×1000×1440 + minuten) "
         f"staat hier per begintijd één teken: de correctie in kwartieren is de tekencode min "
         f"{NUL_TEKEN} ('{chr(NUL_TEKEN)}' = geen). Zo geeft Excel precies dezelfde uren als de app.")
    for rij, (sleutel, tekst) in enumerate(tabel, start=2):
        blad.cell(rij, 1).value = sleutel
        blad.cell(rij, 2).value = tekst  # tekens '(' t/m 'x': nooit een formule of stuurteken
    blad.sheet_state = "hidden"
