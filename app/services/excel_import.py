"""Import uit het oude Excel-rooster (.xlsm), zodat lopende roosterdata niet verloren gaat.

Opbouw van het oude bestand:
- Lijsten:   B = initialen, C = naam, D = contracturen (vanaf rij 2)
             F = dienstnummer, G = omschrijving, H = van, I = tot, J = uren
             N2 = toeslag zaterdag, N3 = toeslag zondag
- Vakanties: A = naam, B = van, C = tot (vanaf rij 2)
- Kalender:  E2 = jaar
- W1..W53:   rij 2 = datums (D, G, J, M, P, S, V), rij 3 = dagopmerkingen
             per medewerker een blok van 4 rijen vanaf rij 4:
               +0 opmerking, +1 opmerkingtijden, +2 dienstnaam, +3 begin/eind/uren
             naam in kolom B, contracturen in Z, weektotaal in Z (+2)
             code-raster: AB = initialen, AC..AI = codes ma..zo op rij 6 + 2n
- De waarde 15 (soms als datum 1900-01-15) betekent 'leeg'.

Werkwijze: eerst een droogloop (lees_bestand) met een voorbeeld van wat er gaat
gebeuren, daarna pas definitief importeren (importeer).
Wachtwoorden en rechten uit de bladen 'Beveiliging' en 'Rechten' worden bewust NIET gelezen.
"""

import logging
import os
import re
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Contracturen, Dagopmerking, Dienst, Dienstcode, Medewerker, Vakantie
from . import instellingen, klok, logboek, sync_planning
from .feestdagen import zorg_voor_jaar
from .kalender import MAX_JAAR, MIN_JAAR, aantal_weken, maandag_van_week
from .medewerkers import uniek_voorstel
from .rooster import UrenContext, markeer_bijgewerkt, uren_voor
from .tijden import is_cijfers
from .urenberekening import bereken_uren, dagfactor
from .voorbeeldpakket import DIENSTCODES

EXCEL_BLANCO = 15
DAG_KOLOMMEN = [4, 7, 10, 13, 16, 19, 22]  # D, G, J, M, P, S, V
CODE_KOLOMMEN = list(range(29, 36))  # AC..AI
MAX_BLOKKEN = 30
UPLOAD_BEWAREN_SECONDEN = 24 * 3600
log = logging.getLogger(__name__)


class ImportFout(Exception):
    """Het bestand is niet te lezen als oud rooster."""


def import_map() -> str:
    """Map voor geüploade Excel-bestanden (alleen tot de import klaar is)."""
    pad = os.path.join(current_app.config["DATA_MAP"], "import")
    os.makedirs(pad, mode=0o700, exist_ok=True)
    return pad


def ruim_oude_uploads_op(nu: float | None = None) -> int:
    """Verwijder geüploade bestanden die er langer dan een dag staan (import afgebroken)."""
    grens = (nu or _time.time()) - UPLOAD_BEWAREN_SECONDEN
    verwijderd = 0
    for naam in os.listdir(import_map()):
        pad = os.path.join(import_map(), naam)
        if os.path.isfile(pad) and os.path.getmtime(pad) < grens:
            os.remove(pad)
            verwijderd += 1
    return verwijderd


# ---------------------------------------------------------------------------
# Hulpfuncties voor celwaarden
# ---------------------------------------------------------------------------

def _is_leeg(waarde) -> bool:
    """Leeg, of de Excel-'blanco' 15 (ook als datum 1900-01-15)."""
    if waarde is None:
        return True
    if isinstance(waarde, str):
        return waarde.strip() in ("", str(EXCEL_BLANCO))
    if isinstance(waarde, datetime) and waarde.year < 1901:
        return True
    if isinstance(waarde, (int, float)) and waarde == EXCEL_BLANCO:
        return True
    return False


def _tijd(waarde) -> str | None:
    """Excel-tijd -> 'HH:MM' (of None)."""
    if _is_leeg(waarde):
        return None
    if isinstance(waarde, datetime):
        waarde = waarde.time()
    if isinstance(waarde, time):
        minuten = round(waarde.hour * 60 + waarde.minute + waarde.second / 60)
    elif isinstance(waarde, (int, float)) and 0 <= waarde < 1:
        minuten = round(waarde * 1440)  # Excel bewaart tijd als deel van een dag
    else:
        return None
    minuten %= 1440
    return f"{minuten // 60:02d}:{minuten % 60:02d}"


def _tekst(waarde) -> str:
    if _is_leeg(waarde) or isinstance(waarde, (datetime, time)):
        return ""
    if isinstance(waarde, float) and waarde.is_integer():
        waarde = int(waarde)
    return str(waarde).strip()


def _getal(waarde) -> float | None:
    if isinstance(waarde, bool) or waarde is None:
        return None
    if isinstance(waarde, (int, float)):
        return float(waarde)
    try:
        return float(str(waarde).replace(",", "."))
    except ValueError:
        return None


def _datum(waarde) -> date | None:
    if isinstance(waarde, datetime):
        return waarde.date()
    if isinstance(waarde, date):
        return waarde
    return None


def _handmatige_uren(d, za: float, zo: float) -> float | None:
    """Uren die in Excel met de hand in de urenkolom zijn gezet, of None.

    Dat zijn:
    - uren bij een dienst zonder tijden (bijv. een cursus of 'TW');
    - uren die afwijken van wat de tijden opleveren. Voorbeeld: dienst 07:15-13:00
      met daarna een training 13:00-17:00 op de opmerkingregel; de planner typte
      dan de uren van de hele dag (9,25). Die nemen we over, precies zoals in Excel.
    """
    if d.excel_uren is None:
        return None
    if not d.begin and not d.eind:
        return d.excel_uren or None
    berekend = bereken_uren(d.begin, d.eind, dagfactor(d.datum, za, zo))
    if berekend is not None and abs(berekend - d.excel_uren) > 0.001:
        return d.excel_uren
    return None


def _nieuwe_uren(d, za: float, zo: float) -> float | None:
    """Uren zoals de webapp ze na de import heeft (handmatige uren gaan voor)."""
    handmatig = _handmatige_uren(d, za, zo)
    if handmatig is not None:
        return handmatig
    return bereken_uren(d.begin, d.eind, dagfactor(d.datum, za, zo))


# ---------------------------------------------------------------------------
# Het plan (resultaat van de droogloop)
# ---------------------------------------------------------------------------

@dataclass
class ImportMedewerker:
    naam: str
    initialen: str
    contracturen: float | None
    bestaand_id: int | None = None
    # Hoe deze medewerker gekoppeld wordt: 'naam' (bestaande medewerker met dezelfde naam),
    # 'initialen' (alleen de initialen zijn bezet: er komt een NIEUWE medewerker) of 'nieuw'
    koppeling: str = "nieuw"
    toelichting: str = ""


@dataclass
class ImportCode:
    nummer: int
    omschrijving: str
    begin: str | None
    eind: str | None
    uren: float | None


@dataclass
class ImportDienst:
    naam: str  # naam van de medewerker (sleutel naar ImportMedewerker)
    datum: date
    code: int | None
    dienstnaam: str
    begin: str | None
    eind: str | None
    opmerking: str
    opm_begin: str | None
    opm_eind: str | None
    excel_uren: float | None


@dataclass
class ImportPlan:
    jaar: int
    toeslag_zaterdag: float | None = None
    toeslag_zondag: float | None = None
    medewerkers: list[ImportMedewerker] = field(default_factory=list)
    codes: list[ImportCode] = field(default_factory=list)
    vakanties: list[tuple[str, date, date]] = field(default_factory=list)
    diensten: list[ImportDienst] = field(default_factory=list)
    dagopmerkingen: dict[date, str] = field(default_factory=dict)
    weken: list[int] = field(default_factory=list)
    # Controle: weektotalen uit Excel (kolom Z) per (naam, week)
    excel_weektotalen: dict[tuple[str, int], float] = field(default_factory=dict)
    waarschuwingen: list[str] = field(default_factory=list)

    @property
    def afwijkend(self) -> int:
        """Aantal diensten waarvan de tijden afwijken van de standaard van de code."""
        standaard = {c.nummer: (c.begin, c.eind) for c in self.codes}
        return sum(1 for d in self.diensten
                   if d.code in standaard and (d.begin, d.eind) != standaard[d.code])

    def handmatige_uren(self) -> list[str]:
        """Diensten waarvan de uren in Excel met de hand afwijken van de tijden.

        Die worden als 'zelf ingevulde uren' overgenomen (zie _handmatige_uren).
        """
        za = self.toeslag_zaterdag or 1.5
        zo = self.toeslag_zondag or 2.0
        regels = []
        for d in self.diensten:
            if not (d.begin or d.eind):
                continue
            handmatig = _handmatige_uren(d, za, zo)
            if handmatig is not None:
                berekend = bereken_uren(d.begin, d.eind, dagfactor(d.datum, za, zo))
                extra = f", opmerking '{d.opmerking}'" if d.opmerking else ""
                regels.append(f"{d.datum:%d-%m-%Y} {d.naam}: {d.begin}-{d.eind}{extra} – "
                              f"tijden geven {berekend:.2f}, Excel {handmatig:.2f} (overgenomen)")
        return regels

    def dubbele_diensten(self) -> list[str]:
        """(medewerker, datum)-combinaties die meer dan eens in het bestand staan."""
        gezien: dict[tuple[str, date], int] = {}
        for d in self.diensten:
            gezien[(d.naam, d.datum)] = gezien.get((d.naam, d.datum), 0) + 1
        return [f"{naam} op {datum:%d-%m-%Y} ({aantal}×)"
                for (naam, datum), aantal in sorted(gezien.items(), key=lambda x: (x[0][1], x[0][0]))
                if aantal > 1]

    def weektotaal_verschillen(self) -> list[str]:
        za = self.toeslag_zaterdag or 1.5
        zo = self.toeslag_zondag or 2.0
        nieuw: dict[tuple[str, int], float] = {}
        for d in self.diensten:
            sleutel = (d.naam, d.datum.isocalendar()[1])
            nieuw[sleutel] = nieuw.get(sleutel, 0) + (_nieuwe_uren(d, za, zo) or 0)
        verschillen = []
        for (naam, week), excel in sorted(self.excel_weektotalen.items(), key=lambda x: (x[0][1], x[0][0])):
            eigen = nieuw.get((naam, week), 0)
            if abs(eigen - excel) > 0.001:
                verschillen.append(f"W{week} {naam}: Excel {excel:.2f}, nieuw {eigen:.2f}")
        return verschillen


# ---------------------------------------------------------------------------
# Lezen (droogloop)
# ---------------------------------------------------------------------------

def lees_bestand(pad: str) -> ImportPlan:
    """Lees het Excel-bestand en maak een plan. Er wordt nog niets opgeslagen."""
    import openpyxl

    try:
        # data_only: de laatst berekende waarden (datums, totalen) in plaats van formules
        boek = openpyxl.load_workbook(pad, data_only=True, keep_vba=False)
    except Exception as fout:  # elk leesprobleem is een importfout
        raise ImportFout(f"Het bestand kan niet gelezen worden: {fout}") from fout
    if "Lijsten" not in boek.sheetnames:
        raise ImportFout("Dit lijkt geen oud rooster: het blad 'Lijsten' ontbreekt.")

    jaar = None
    if "Kalender" in boek.sheetnames:
        jaar = int(_getal(boek["Kalender"]["E2"].value) or 0) or None
    if jaar is not None and not MIN_JAAR <= jaar <= MAX_JAAR:
        raise ImportFout(f"Het jaar in Kalender!E2 ({jaar}) is ongeldig; verwacht een jaar tussen "
                         f"{MIN_JAAR} en {MAX_JAAR}.")
    plan = ImportPlan(jaar=jaar or klok.vandaag().year)
    _lees_lijsten(boek["Lijsten"], plan)
    _bepaal_koppelingen(plan)
    if "Vakanties" in boek.sheetnames:
        _lees_vakanties(boek["Vakanties"], plan)

    weekbladen = sorted(
        (int(naam[1:]), naam) for naam in boek.sheetnames if re.fullmatch(r"W\d{1,2}", naam))
    for week, naam in weekbladen:
        if week > aantal_weken(plan.jaar):
            if _blad_heeft_diensten(boek[naam]):
                plan.waarschuwingen.append(f"{naam} overgeslagen: {plan.jaar} heeft geen week {week}.")
            continue
        _lees_weekblad(boek[naam], week, plan)
    if dubbel := plan.dubbele_diensten():
        plan.waarschuwingen.append(
            "Dubbele diensten (zelfde medewerker en dag staan er meer dan eens in): "
            + "; ".join(dubbel) + ". Pas het Excel-bestand aan; zo kan het niet geïmporteerd worden.")
    log.debug("Excel gelezen: jaar %s, %s medewerkers, %s codes, %s diensten, %s weken, "
              "%s waarschuwingen", plan.jaar, len(plan.medewerkers), len(plan.codes),
              len(plan.diensten), len(plan.weken), len(plan.waarschuwingen))
    return plan


def _bepaal_koppelingen(plan: ImportPlan) -> None:
    """Bepaal per Excel-medewerker of hij aan een bestaande medewerker gekoppeld wordt.

    Alleen een gelijke naam koppelt automatisch. Zijn alleen de initialen gelijk, dan
    is het waarschijnlijk iemand anders: er komt een nieuwe medewerker (met unieke
    initialen) en de droogloop toont een waarschuwing.
    """
    for im in plan.medewerkers:
        bestaand = Medewerker.query.filter_by(naam=im.naam).first()
        if bestaand is not None:
            im.bestaand_id, im.koppeling = bestaand.id, "naam"
            im.toelichting = "bestaande medewerker (zelfde naam)"
            continue
        andere = Medewerker.query.filter_by(initialen=im.initialen).first() if im.initialen else None
        if andere is not None:
            im.koppeling = "initialen"
            im.toelichting = f"nieuw; initialen {im.initialen} zijn al van {andere.naam}"
            plan.waarschuwingen.append(
                f"'{im.naam}' heeft dezelfde initialen ({im.initialen}) als de bestaande medewerker "
                f"'{andere.naam}'. Er wordt een nieuwe medewerker aangemaakt met andere initialen. "
                "Is het dezelfde persoon? Pas dan eerst de naam in de app of in Excel aan.")
        else:
            im.toelichting = "nieuwe medewerker"


def _lees_lijsten(blad, plan: ImportPlan) -> None:
    for rij in range(2, 200):
        naam = _tekst(blad.cell(rij, 3).value)
        if not naam:
            continue
        plan.medewerkers.append(ImportMedewerker(
            naam=naam,
            initialen=_tekst(blad.cell(rij, 2).value).upper(),
            contracturen=_getal(blad.cell(rij, 4).value),
        ))
    for rij in range(2, 200):
        nummer = _getal(blad.cell(rij, 6).value)
        omschrijving = _tekst(blad.cell(rij, 7).value)
        if nummer is None or int(nummer) == EXCEL_BLANCO or not omschrijving:
            continue
        plan.codes.append(ImportCode(
            nummer=int(nummer), omschrijving=omschrijving,
            begin=_tijd(blad.cell(rij, 8).value), eind=_tijd(blad.cell(rij, 9).value),
            uren=_getal(blad.cell(rij, 10).value),
        ))
    plan.toeslag_zaterdag = _getal(blad["N2"].value)
    plan.toeslag_zondag = _getal(blad["N3"].value)


def _lees_vakanties(blad, plan: ImportPlan) -> None:
    for rij in range(2, 200):
        naam = _tekst(blad.cell(rij, 1).value)
        van, tot = _datum(blad.cell(rij, 2).value), _datum(blad.cell(rij, 3).value)
        if naam and van and tot:
            plan.vakanties.append((naam, van, tot))


def _blad_heeft_diensten(blad) -> bool:
    return any(not _is_leeg(blad.cell(6 + 2 * n, k).value)
               for n in range(MAX_BLOKKEN // 3) for k in CODE_KOLOMMEN)


def _lees_weekblad(blad, week: int, plan: ImportPlan) -> None:
    maandag = _datum(blad.cell(2, DAG_KOLOMMEN[0]).value) or maandag_van_week(plan.jaar, week)
    if maandag.isocalendar()[:2] != (plan.jaar, week):
        plan.waarschuwingen.append(
            f"W{week}: datum in het blad ({maandag:%d-%m-%Y}) past niet bij week {week}; "
            "de ISO-week wordt aangehouden.")
        maandag = maandag_van_week(plan.jaar, week)
    dagen = [maandag + timedelta(days=i) for i in range(7)]
    plan.weken.append(week)

    for i, kolom in enumerate(DAG_KOLOMMEN):
        tekst = _tekst(blad.cell(3, kolom).value)
        if tekst:
            plan.dagopmerkingen[dagen[i]] = tekst

    namen = {m.naam for m in plan.medewerkers}
    for n in range(MAX_BLOKKEN):
        basis = 4 + 4 * n
        naam = _tekst(blad.cell(basis, 2).value)
        if is_cijfers(naam):  # bijv. 0 uit een formule naar een lege cel
            naam = ""
        if not naam:
            if n > 12 and all(_is_leeg(blad.cell(basis + k, 2).value) for k in range(8)):
                break
            continue
        if naam not in namen:
            plan.waarschuwingen.append(f"W{week}: '{naam}' staat niet in Lijsten; overgeslagen.")
            continue
        excel_totaal = _getal(blad.cell(basis + 2, 26).value)  # kolom Z
        heeft_dienst = False
        for i, kolom in enumerate(DAG_KOLOMMEN):
            code_waarde = blad.cell(6 + 2 * n, CODE_KOLOMMEN[i]).value if n < 11 else None
            code = None if _is_leeg(code_waarde) else _getal(code_waarde)
            dienst = ImportDienst(
                naam=naam, datum=dagen[i],
                code=int(code) if code is not None else None,
                dienstnaam=_tekst(blad.cell(basis + 2, kolom).value),
                begin=_tijd(blad.cell(basis + 3, kolom).value),
                eind=_tijd(blad.cell(basis + 3, kolom + 1).value),
                opmerking=_tekst(blad.cell(basis, kolom).value),
                opm_begin=_tijd(blad.cell(basis + 1, kolom).value),
                opm_eind=_tijd(blad.cell(basis + 1, kolom + 1).value),
                excel_uren=_getal(blad.cell(basis + 3, kolom + 2).value),
            )
            if (dienst.code is None and not dienst.dienstnaam and not dienst.begin
                    and not dienst.eind and not dienst.opmerking and not dienst.opm_begin):
                continue
            plan.diensten.append(dienst)
            heeft_dienst = True
        if heeft_dienst and excel_totaal is not None:
            plan.excel_weektotalen[(naam, week)] = excel_totaal


# ---------------------------------------------------------------------------
# Definitief importeren
# ---------------------------------------------------------------------------

def importeer(plan: ImportPlan) -> dict:
    """Schrijf het plan naar de database, in één transactie (alles of niets).

    Bestaande diensten in de geïmporteerde weken worden overschreven; bestaande
    medewerkers (zelfde naam) en codes (zelfde nummer) worden hergebruikt.
    Gaat er iets mis, dan wordt alles teruggedraaid en volgt een ImportFout.
    """
    if dubbel := plan.dubbele_diensten():
        raise ImportFout("Er is niets geïmporteerd: dubbele diensten in het bestand ("
                         + "; ".join(dubbel) + ").")
    try:
        resultaat, medewerkers = _importeer(plan)
        db.session.commit()
    except IntegrityError as fout:
        db.session.rollback()
        raise ImportFout("Er is niets geïmporteerd: het bestand bevat gegevens die botsen "
                         f"(bijvoorbeeld een dubbele dienst). Details: {fout.orig}") from fout
    except Exception:
        db.session.rollback()
        raise
    # Gekoppelde agenda's gelijk maken aan het nieuwe rooster. De import zelf is al
    # opgeslagen: een fout hier mag niet als 'import mislukt' gemeld worden.
    for medewerker in medewerkers:
        try:
            sync_planning.plan_volledig(medewerker)
        except Exception:
            db.session.rollback()
            log.exception("Agenda-synchronisatie na de import niet gepland voor %s; "
                          "gebruik Beheer → Google Agenda → Volledig synchroniseren", medewerker.naam)
    log.info("Excel-import klaar: %s", resultaat)
    return resultaat


def _importeer(plan: ImportPlan) -> tuple[dict, list[Medewerker]]:
    """Het eigenlijke importeren; er wordt hier nergens gecommit."""
    resultaat = {"medewerkers": 0, "codes": 0, "vakanties": 0, "diensten": 0, "dagopmerkingen": 0}

    # Feestdagen vooraf aanmaken (zonder commit), zodat de berekeningen hieronder
    # nooit halverwege iets opslaan. Een week kan over de jaargrens lopen.
    for jaar in (plan.jaar - 1, plan.jaar, plan.jaar + 1):
        zorg_voor_jaar(jaar, commit=False)

    # Toeslagen (oude waarde in het logboek)
    for sleutel, waarde in (("toeslag_zaterdag", plan.toeslag_zaterdag),
                            ("toeslag_zondag", plan.toeslag_zondag)):
        if waarde and instellingen.lees(sleutel) != str(waarde):
            logboek.log("Instelling gewijzigd", "Excel-import", veld=sleutel,
                        oud=instellingen.lees(sleutel), nieuw=waarde)
            instellingen.schrijf(sleutel, waarde)

    # Dienstcodes (kleuren uit het voorbeeldpakket als het nummer daar in staat)
    pakket = {c[0]: c for c in DIENSTCODES}
    codes: dict[int, Dienstcode] = {c.nummer: c for c in Dienstcode.query.all()}
    for ic in plan.codes:
        if ic.nummer in codes:
            continue
        uit_pakket = pakket.get(ic.nummer)
        code = Dienstcode(
            nummer=ic.nummer, omschrijving=ic.omschrijving, std_begin=ic.begin, std_eind=ic.eind,
            std_uren=ic.uren,
            kleur_achtergrond=uit_pakket[5] if uit_pakket else "#D9D9D9",
            kleur_tekst=uit_pakket[6] if uit_pakket else "#000000",
            vet=True, cursief=uit_pakket[7] if uit_pakket else False,
            hele_dag_zonder_tijden=ic.begin is None,
        )
        db.session.add(code)
        codes[ic.nummer] = code
        resultaat["codes"] += 1
    per_naam_code = {}
    for code in codes.values():
        per_naam_code.setdefault(code.omschrijving.casefold(), []).append(code)

    # Medewerkers: alleen op naam hergebruiken (zie _bepaal_koppelingen)
    medewerkers: dict[str, Medewerker] = {}
    volgorde = db.session.query(db.func.max(Medewerker.volgorde)).scalar() or 0
    for im in plan.medewerkers:
        medewerker = Medewerker.query.filter_by(naam=im.naam).first()
        if medewerker is None:
            volgorde += 1
            initialen = im.initialen if im.initialen and not Medewerker.query.filter_by(
                initialen=im.initialen).first() else uniek_voorstel(im.naam)
            medewerker = Medewerker(naam=im.naam, initialen=initialen or f"M{volgorde}",
                                    volgorde=volgorde)
            db.session.add(medewerker)
            db.session.flush()
            resultaat["medewerkers"] += 1
        if im.contracturen is not None:
            bestaand = next((c for c in medewerker.contracturen if c.jaar == plan.jaar), None)
            if bestaand:
                bestaand.uren = im.contracturen
            else:
                medewerker.contracturen.append(Contracturen(jaar=plan.jaar, uren=im.contracturen))
        medewerkers[im.naam] = medewerker

    # Vakanties
    for naam, van, tot in plan.vakanties:
        if not Vakantie.query.filter_by(naam=naam, datum_van=van).first():
            db.session.add(Vakantie(naam=naam, datum_van=van, datum_tot=tot))
            resultaat["vakanties"] += 1
    db.session.flush()

    # Bestaande diensten in de geïmporteerde weken van deze medewerkers verwijderen
    if plan.weken:
        van = maandag_van_week(plan.jaar, min(plan.weken))
        tot = maandag_van_week(plan.jaar, max(plan.weken)) + timedelta(days=6)
        ids = [m.id for m in medewerkers.values()]
        Dienst.query.filter(Dienst.datum >= van, Dienst.datum <= tot,
                            Dienst.medewerker_id.in_(ids)).delete(synchronize_session="fetch")
        context = UrenContext(van, tot)
    else:
        context = None

    za = plan.toeslag_zaterdag or 1.5
    zo = plan.toeslag_zondag or 2.0
    for d in plan.diensten:
        medewerker = medewerkers.get(d.naam)
        if medewerker is None:
            continue
        code = codes.get(d.code) if d.code is not None else None
        if code is None and d.dienstnaam:
            # Geen (bekende) code maar wel een naam: code op naam zoeken als die uniek is
            kandidaten = per_naam_code.get(d.dienstnaam.casefold(), [])
            code = kandidaten[0] if len(kandidaten) == 1 else None
        dienst = Dienst(
            medewerker_id=medewerker.id, datum=d.datum,
            dienstcode_id=code.id if code else None,
            dienstnaam_override="" if code else d.dienstnaam[:60],
            begin=d.begin, eind=d.eind,
            tijden_handmatig=bool(code and (d.begin, d.eind) != (code.std_begin, code.std_eind)),
            opmerking_tekst=d.opmerking[:120], opmerking_begin=d.opm_begin,
            opmerking_eind=d.opm_eind, versie=1,
            # Met de hand getypte uren uit Excel overnemen (zie _handmatige_uren)
            uren_handmatig=_handmatige_uren(d, za, zo),
        )
        dienst.uren_berekend = uren_voor(dienst, context)
        db.session.add(dienst)
        resultaat["diensten"] += 1

    # Dagopmerkingen: alleen opslaan als ze afwijken van de automatische tekst
    from .weekrooster import automatische_dagopmerkingen

    if plan.dagopmerkingen:
        db.session.flush()
        automatisch = automatische_dagopmerkingen(min(plan.dagopmerkingen), max(plan.dagopmerkingen))
        for dag, tekst in plan.dagopmerkingen.items():
            if automatisch.get(dag, "") == tekst:
                continue
            bestaand = Dagopmerking.query.filter_by(datum=dag).first()
            if bestaand:
                bestaand.tekst = tekst
            else:
                db.session.add(Dagopmerking(datum=dag, tekst=tekst, handmatig=True))
            resultaat["dagopmerkingen"] += 1

    logboek.log("Excel-import", ", ".join(f"{k}: {v}" for k, v in resultaat.items()))
    markeer_bijgewerkt()
    db.session.flush()
    return resultaat, list(medewerkers.values())
