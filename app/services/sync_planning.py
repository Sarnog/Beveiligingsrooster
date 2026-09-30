"""Taken inplannen voor de Google Agenda-synchronisatie.

Een roosterwijziging zet een taak in de tabel 'sync_wachtrij'. De worker
verwerkt die later; de webpagina wacht dus nooit op Google.

Samenvoegen (debounce): staat er voor dezelfde medewerker + datum al een
wachtende taak, dan schuiven we die een paar seconden op in plaats van een
nieuwe toe te voegen. Tien snelle wijzigingen leveren zo één API-call op.
"""

from datetime import date, timedelta

from ..extensions import db
from ..models import Dienst, Medewerker, SyncTaak
from . import klok

DEBOUNCE_SECONDEN = 10


def _is_gekoppeld(medewerker: Medewerker | None) -> bool:
    return bool(medewerker and medewerker.agenda_modus and medewerker.agenda_id)


def plan_dag(medewerker: Medewerker, datum: date, commit: bool = True) -> None:
    """Plan een synchronisatie van één dag van één medewerker."""
    if not _is_gekoppeld(medewerker):
        return
    straks = klok.nu() + timedelta(seconds=DEBOUNCE_SECONDEN)
    bestaand = SyncTaak.query.filter_by(
        medewerker_id=medewerker.id, datum=datum, soort="dag", status="wacht"
    ).first()
    if bestaand:
        bestaand.niet_voor = straks  # samenvoegen: later uitvoeren, één keer
    else:
        db.session.add(SyncTaak(medewerker_id=medewerker.id, datum=datum, soort="dag",
                                niet_voor=straks))
    if commit:
        db.session.commit()


def plan_diensten(diensten: list[Dienst]) -> None:
    """Plan de dagen van een lijst diensten."""
    for dienst in diensten:
        plan_dag(dienst.medewerker, dienst.datum, commit=False)
    db.session.commit()


def plan_toekomst(medewerker: Medewerker) -> None:
    """Plan alle toekomstige dagen met een dienst opnieuw (bijv. na een naamwijziging)."""
    if not _is_gekoppeld(medewerker):
        return
    diensten = Dienst.query.filter(
        Dienst.medewerker_id == medewerker.id, Dienst.datum >= klok.vandaag()
    ).all()
    plan_diensten(diensten)


def plan_volledig(medewerker: Medewerker) -> None:
    """Plan een volledige synchronisatie (maakt de agenda gelijk aan het rooster)."""
    if not _is_gekoppeld(medewerker):
        return
    bestaand = SyncTaak.query.filter_by(
        medewerker_id=medewerker.id, soort="volledig", status="wacht"
    ).first()
    if not bestaand:
        db.session.add(SyncTaak(medewerker_id=medewerker.id, soort="volledig",
                                niet_voor=klok.nu()))
    db.session.commit()
