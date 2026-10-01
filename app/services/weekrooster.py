"""Het weekrooster: gegevens ophalen en cellen wijzigen.

Een 'cel' is één veld van één medewerker op één dag:
    code        dienstcode-nummer (code-raster)
    begin/eind  tijden van de dienst (regel d)
    opmerking   vrije tekst (regel a)
    opm_begin / opm_eind   tijden bij de opmerking (regel b)
Daarnaast is er per dag de 'dagopmerking' (rij 3 van het Excel-blad).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Dagopmerking, Dienst, Dienstcode, Medewerker, OpmerkingKleurregel
from . import instellingen, klok, logboek, sync_planning
from .feestdagen import feestdagen_in_periode, vakantiedagen_in_periode, zorg_voor_jaar
from .kalender import dagen_van_week
from .rooster import UrenContext, markeer_bijgewerkt, uren_voor
from .tijden import OngeldigeTijd, is_cijfers, normaliseer_tijd
from .urenberekening import formatteer_uren

VELDEN = ("code", "begin", "eind", "opmerking", "opm_begin", "opm_eind", "dienstnaam", "uren")
VELD_NAMEN = {
    "code": "dienstcode", "begin": "begintijd", "eind": "eindtijd", "opmerking": "opmerking",
    "opm_begin": "opmerking begin", "opm_eind": "opmerking eind",
    "dienstnaam": "dienstnaam", "uren": "uren",
}
MAX_OPMERKING = 120

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


# ---------------------------------------------------------------------------
# Dagopmerkingen (automatisch uit feestdagen/vakanties, of handmatig)
# ---------------------------------------------------------------------------

def automatische_dagopmerkingen(van: date, tot: date) -> dict[date, str]:
    """Feestdag gaat voor vakantie. Vakantie alleen op werkdagen (zoals in Excel)."""
    teksten = dict(vakantiedagen_in_periode(van, tot))
    teksten.update(feestdagen_in_periode(van, tot))
    return teksten


def dagopmerkingen(dagen: list[date]) -> dict[date, dict]:
    """Per dag: {'tekst': ..., 'handmatig': bool}."""
    automatisch = automatische_dagopmerkingen(dagen[0], dagen[-1])
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


def medewerkers_voor_periode(van: date, tot: date) -> list[Medewerker]:
    """Medewerkers in het rooster: niet gearchiveerd op de eerste dag, of met diensten."""
    met_diensten = {
        mid for (mid,) in db.session.query(Dienst.medewerker_id)
        .filter(Dienst.datum >= van, Dienst.datum <= tot).distinct()
    }
    alle = Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()
    return [m for m in alle if m.is_zichtbaar_op(van) or m.id in met_diensten]


def week_gegevens(jaar: int, week: int) -> dict:
    """Alles voor de weekpagina: dagen, dagopmerkingen en per medewerker de 7 dagen."""
    dagen = dagen_van_week(jaar, week)
    medewerkers = medewerkers_voor_periode(dagen[0], dagen[-1])
    diensten = Dienst.query.filter(Dienst.datum >= dagen[0], Dienst.datum <= dagen[-1]).all()
    per_sleutel = {(d.medewerker_id, d.datum): d for d in diensten}
    regels = kleurregels()

    rijen = []
    for medewerker in medewerkers:
        rij = WeekRij(medewerker=medewerker, contracturen=medewerker.contracturen_voor(jaar))
        for dag in dagen:
            dienst = per_sleutel.get((medewerker.id, dag))
            rij.dagen.append(dienst_naar_dict(dienst, regels))
            if dienst is not None:
                rij.heeft_diensten = True
                rij.weektotaal += dienst.uren_berekend or 0
        rijen.append(rij)

    return {
        "jaar": jaar,
        "week": week,
        "dagen": dagen,
        "dagopmerkingen": dagopmerkingen(dagen),
        "feestdagen": feestdagen_in_periode(dagen[0], dagen[-1]),
        "rijen": rijen,
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


def _tijd(waarde: str) -> str | None:
    try:
        return normaliseer_tijd(waarde)
    except OngeldigeTijd as fout:
        raise CelFout(f"{fout}. Gebruik bijvoorbeeld 715, 7:15 of 07.15.") from fout


def _pas_veld_toe(dienst: Dienst, veld: str, waarde: str) -> tuple[str, str]:
    """Wijzig één veld van een dienst. Geeft (oude waarde, nieuwe waarde) als tekst."""
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
        if dienst.dienstcode is not None and tekst == dienst.dienstcode.omschrijving:
            return oud, oud  # niets veranderd
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
    fouten: list[dict] = []
    geclaimd: set[tuple[int, date]] = set()
    geraakt: dict[tuple[int, date], Dienst | None] = {}
    gecontroleerd: set[tuple[int, date]] = set()
    medewerkers: dict[int, Medewerker] = {}
    context_cache: dict[date, UrenContext] = {}

    for w in wijzigingen:
        sleutel = (w.medewerker_id, w.datum)
        medewerker = medewerkers.get(w.medewerker_id) or db.session.get(Medewerker, w.medewerker_id)
        if medewerker is None:
            fouten.append({"mw": w.medewerker_id, "datum": w.datum.isoformat(), "veld": w.veld,
                           "melding": "Onbekende medewerker."})
            continue
        medewerkers[medewerker.id] = medewerker

        dienst = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=w.datum).first()
        huidige_versie = dienst.versie if dienst else 0
        # Optimistic locking: alleen de eerste keer per dienst in dit verzoek controleren
        if w.versie is not None and sleutel not in gecontroleerd and w.versie != huidige_versie:
            fouten.append({"mw": medewerker.id, "datum": w.datum.isoformat(), "veld": w.veld,
                           "melding": "Deze cel is net door iemand anders gewijzigd. "
                                      "De nieuwste waarde staat nu in beeld.",
                           "conflict": True})
            geraakt[sleutel] = dienst
            continue
        gecontroleerd.add(sleutel)

        nieuw_record = dienst is None
        if nieuw_record:
            # Nog niet aan de sessie toevoegen: pas als de wijziging geldig is
            dienst = Dienst(medewerker_id=medewerker.id, datum=w.datum, versie=0,
                            dienstnaam_override="", opmerking_tekst="", tijden_handmatig=False)
        try:
            with db.session.no_autoflush:
                oud, nieuw = _pas_veld_toe(dienst, w.veld, w.waarde)
        except CelFout as fout:
            fouten.append({"mw": medewerker.id, "datum": w.datum.isoformat(), "veld": w.veld,
                           "melding": str(fout)})
            geraakt[sleutel] = None if nieuw_record else dienst
            continue

        if oud == nieuw:
            geraakt[sleutel] = None if nieuw_record else dienst
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
                    veld=VELD_NAMEN.get(w.veld, w.veld), oud=oud, nieuw=nieuw)
        sync_planning.plan_dag(medewerker, w.datum, commit=False)

        # Een helemaal lege regel ruimen we op (behalve als er nog een agenda-afspraak
        # aan hangt: die moet de worker eerst verwijderen)
        if dienst.is_leeg and not dienst.google_event_id:
            if nieuw_record:
                db.session.expunge(dienst)
            else:
                db.session.delete(dienst)
        db.session.flush()  # zodat een volgende cel van dezelfde dag deze dienst terugvindt
        geraakt[sleutel] = dienst

    return set(geraakt), fouten


def verwerk_rooster(wijzigingen: list[Wijziging], dag_wijzigingen=(), opslaan: bool = True,
                    ook_tonen=(), ook_dagen=()) -> dict:
    """Verwerk wijzigingen in het rooster: opslaan, of alleen een voorbeeld berekenen.

    opslaan=False: alles wordt uitgerekend (dienstnaam, standaardtijden, uren,
    weektotalen) en teruggegeven, maar daarna teruggedraaid. Zo ziet de planner
    direct het resultaat, terwijl er pas iets bewaard wordt bij 'Opslaan'.

    ook_tonen / ook_dagen: extra dagen waarvan de actuele stand mee terug moet
    (bijv. na 'ongedaan maken', zodat die cellen hun oude waarde weer tonen).
    Geeft {'bijgewerkt': {...}, 'dagopmerkingen': {...}, 'fouten': [...]}.
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
            actueel = Dienst.query.filter_by(medewerker_id=mw, datum=datum).first()
            gegevens = dienst_naar_dict(actueel, regels)
            gegevens["weektotaal"] = formatteer_uren(weektotaal(mw, datum))
            bijgewerkt[f"{mw}|{datum.isoformat()}"] = gegevens
        dagen = sorted({d for d, _ in dag_wijzigingen} | set(ook_dagen))
        dagresultaat = {d.isoformat(): v for d, v in dagopmerkingen(dagen).items()} if dagen else {}

        if opslaan:
            db.session.commit()
        else:
            db.session.rollback()  # alleen een voorbeeld: niets bewaren
    except VersieConflict:
        db.session.rollback()
        raise
    except IntegrityError as fout:  # tegelijk door een ander aangemaakt
        db.session.rollback()
        raise VersieConflict("Iemand anders wijzigde tegelijk dezelfde dienst.") from fout
    return {"bijgewerkt": bijgewerkt, "dagopmerkingen": dagresultaat, "fouten": fouten}


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
        (d.medewerker_id, d.datum): d for d in Dienst.query.filter(
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
            origineel = bron.get((medewerker.id, dag_bron))
            doel = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=dag_doel).first()
            if origineel is None and doel is None:
                continue
            if doel is None:
                doel = Dienst(medewerker_id=medewerker.id, datum=dag_doel, versie=0)
                db.session.add(doel)
            for kolom, leeg in LEGE_DIENST.items():
                setattr(doel, kolom, getattr(origineel, kolom) if origineel else leeg)
            doel.uren_berekend = uren_voor(doel, context)
            doel.versie = (doel.versie or 0) + 1
            sync_planning.plan_dag(medewerker, dag_doel, commit=False)
            if doel.is_leeg and not doel.google_event_id:
                if doel in db.session.new:
                    db.session.expunge(doel)
                else:
                    db.session.delete(doel)
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
        .order_by(Dienst.datum).all()
    )
