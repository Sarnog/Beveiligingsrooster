"""Berekeningen voor de kalender, het urenoverzicht en zoeken."""

from dataclasses import dataclass
from datetime import date, timedelta

from ..extensions import db
from ..models import Dienst, Dienstcode, Feestdag, Medewerker
from . import klok
from .feestdagen import feestdagen_in_periode, vakantiedagen_in_periode, zorg_voor_jaar
from .kalender import MAANDNAMEN, aantal_weken, eerste_en_laatste_dag_isojaar, maand_raster


@dataclass
class OverzichtRij:
    medewerker: Medewerker
    contracturen: float | None
    gewerkt: float
    per_week: dict[int, float]

    @property
    def verschil(self) -> float | None:
        if self.contracturen is None:
            return None
        return self.gewerkt - self.contracturen


def medewerkers_in_jaar(jaar: int) -> list[Medewerker]:
    """Medewerkers die in (een deel van) het ISO-jaar actief waren of uren hebben."""
    eerste, laatste = eerste_en_laatste_dag_isojaar(jaar)
    met_diensten = {
        mid for (mid,) in db.session.query(Dienst.medewerker_id)
        .filter(Dienst.datum >= eerste, Dienst.datum <= laatste).distinct()
    }
    alle = Medewerker.query.order_by(Medewerker.volgorde, Medewerker.naam).all()
    return [m for m in alle if m.is_zichtbaar_op(eerste) or m.id in met_diensten]


def uren_overzicht(jaar: int) -> list[OverzichtRij]:
    """Per medewerker de weektotalen (W1..W52/53) en het jaartotaal van een ISO-jaar.

    Jaartotaal = som van alle weektotalen in dat ISO-jaar (zoals in Excel: W1 t/m W53).
    """
    eerste, laatste = eerste_en_laatste_dag_isojaar(jaar)
    diensten = (
        db.session.query(Dienst.medewerker_id, Dienst.datum, Dienst.uren_berekend)
        .filter(Dienst.datum >= eerste, Dienst.datum <= laatste,
                Dienst.uren_berekend.isnot(None))
        .all()
    )
    per_medewerker: dict[int, dict[int, float]] = {}
    for mid, datum, uren in diensten:
        week = datum.isocalendar()[1]
        weken = per_medewerker.setdefault(mid, {})
        weken[week] = weken.get(week, 0) + uren

    rijen = []
    for medewerker in medewerkers_in_jaar(jaar):
        per_week = per_medewerker.get(medewerker.id, {})
        rijen.append(OverzichtRij(
            medewerker=medewerker,
            contracturen=medewerker.contracturen_voor(jaar),
            gewerkt=sum(per_week.values()),
            per_week=per_week,
        ))
    return rijen


def jaarkalender(jaar: int) -> list[dict]:
    """12 maandblokken met per dag de kleurklasse (vandaag > feestdag > vakantie > weekend)."""
    zorg_voor_jaar(jaar)
    begin, einde = date(jaar, 1, 1), date(jaar, 12, 31)
    feestdagen = feestdagen_in_periode(begin, einde)
    vakanties = vakantiedagen_in_periode(begin, einde)
    vandaag = klok.vandaag()

    maanden = []
    for maand in range(1, 13):
        weken = []
        for rij in maand_raster(jaar, maand):
            eerste_dag = next(d for d in rij if d is not None)
            iso_jaar, iso_week, _ = eerste_dag.isocalendar()
            dagen = []
            for dag in rij:
                if dag is None:
                    dagen.append(None)
                    continue
                if dag == vandaag:
                    klasse = "vandaag"
                elif dag in feestdagen:
                    klasse = "feestdag"
                elif dag in vakanties:
                    klasse = "vakantie"
                elif dag.weekday() >= 5:
                    klasse = "weekend"
                else:
                    klasse = ""
                titel = feestdagen.get(dag) or vakanties.get(dag) or ""
                dagen.append({"datum": dag, "klasse": klasse, "titel": titel})
            weken.append({"iso_jaar": iso_jaar, "week": iso_week, "dagen": dagen})
        maanden.append({"nummer": maand, "naam": MAANDNAMEN[maand - 1], "weken": weken})
    return maanden


def roostervrije_dagen(jaar: int) -> list[Feestdag]:
    zorg_voor_jaar(jaar)
    return Feestdag.query.filter_by(jaar=jaar, actief=True).order_by(Feestdag.datum).all()


def weken_lijst(jaar: int) -> list[int]:
    return list(range(1, aantal_weken(jaar) + 1))


# ---------------------------------------------------------------------------
# Zoeken
# ---------------------------------------------------------------------------

MIN_NAAM = 3


def zoek_diensten(naam: str = "", code: int | None = None, van: date | None = None,
                  tot: date | None = None, limiet: int = 5000) -> list[Dienst]:
    """Zoek diensten op naam/initialen (deelmatch), dienstcode en periode.

    Alleen regels met een dienst (code of vrije dienstnaam) tellen mee, zoals in Excel.
    """
    query = Dienst.query.join(Medewerker, Dienst.medewerker_id == Medewerker.id).outerjoin(
        Dienstcode, Dienst.dienstcode_id == Dienstcode.id)
    query = query.filter(
        db.or_(Dienst.dienstcode_id.isnot(None), Dienst.dienstnaam_override != ""))
    naam = (naam or "").strip()
    if naam:
        # % en _ letterlijk zoeken (anders vindt '___' alles en omzeil je de minimale lengte)
        schoon = naam.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        patroon = f"%{schoon}%"
        query = query.filter(db.or_(Medewerker.naam.ilike(patroon, escape="\\"),
                                    Medewerker.initialen.ilike(patroon, escape="\\")))
    if code is not None:
        query = query.filter(Dienstcode.nummer == code)
    if van:
        query = query.filter(Dienst.datum >= van)
    if tot:
        query = query.filter(Dienst.datum <= tot)
    return query.order_by(Dienst.datum, Medewerker.volgorde).limit(limiet).all()


def week_bereik(datum: date) -> tuple[date, date]:
    maandag = datum - timedelta(days=datum.weekday())
    return maandag, maandag + timedelta(days=6)
