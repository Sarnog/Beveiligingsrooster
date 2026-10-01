"""Feestdagen en vakanties uit de database, per jaar of periode."""

from datetime import date, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..extensions import db
from ..models import Feestdag, Vakantie
from .kalender import nederlandse_feestdagen


def zorg_voor_jaar(jaar: int, commit: bool = True) -> None:
    """Maak de standaard feestdagen van een jaar aan als die er nog niet zijn.

    Bestaande regels (ook uitgezette) blijven ongemoeid, zodat keuzes van de
    beheerder bewaard blijven. commit=False: alleen in de sessie zetten (flush),
    zodat de aanroeper alles in één transactie kan opslaan of terugdraaien.
    """
    bestaande = _bestaande_sleutels(jaar)
    nieuw = [{"jaar": jaar, "datum": datum, "naam": naam, "sleutel": sleutel, "actief": True}
             for sleutel, naam, datum in nederlandse_feestdagen(jaar) if sleutel not in bestaande]
    if not nieuw:
        return
    # Maakt een ander proces ze tegelijk aan, dan slaat de unieke index ze gewoon over
    db.session.execute(sqlite_insert(Feestdag).values(nieuw).on_conflict_do_nothing())
    if commit:
        db.session.commit()


def _bestaande_sleutels(jaar: int) -> set[str]:
    return {f.sleutel for f in Feestdag.query.filter_by(jaar=jaar).all() if f.sleutel}


def feestdagen_in_periode(van: date, tot: date) -> dict[date, str]:
    """Actieve feestdagen tussen van en tot (inclusief) als {datum: naam}."""
    for jaar in range(van.year, tot.year + 1):
        zorg_voor_jaar(jaar)
    rijen = (
        Feestdag.query.filter(Feestdag.actief.is_(True))
        .filter(Feestdag.datum >= van, Feestdag.datum <= tot)
        .order_by(Feestdag.datum)
        .all()
    )
    resultaat: dict[date, str] = {}
    for rij in rijen:
        # Twee feestdagen op één dag: namen samenvoegen
        if rij.datum in resultaat:
            resultaat[rij.datum] += " / " + rij.naam
        else:
            resultaat[rij.datum] = rij.naam
    return resultaat


def vakantiedagen_in_periode(van: date, tot: date) -> dict[date, str]:
    """Vakantie-werkdagen (ma-vr) tussen van en tot als {datum: vakantienaam}."""
    rijen = (
        Vakantie.query.filter(Vakantie.datum_tot >= van, Vakantie.datum_van <= tot)
        .order_by(Vakantie.datum_van)
        .all()
    )
    resultaat: dict[date, str] = {}
    for vakantie in rijen:
        dag = max(vakantie.datum_van, van)
        einde = min(vakantie.datum_tot, tot)
        while dag <= einde:
            if dag.weekday() < 5:  # alleen werkdagen, zoals in Excel
                resultaat.setdefault(dag, vakantie.naam)
            dag += timedelta(days=1)
    return resultaat
