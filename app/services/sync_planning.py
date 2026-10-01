"""Taken inplannen voor de Google Agenda-synchronisatie.

Een roosterwijziging zet een taak in de tabel 'sync_wachtrij'. De worker
verwerkt die later; de webpagina wacht dus nooit op Google.

Samenvoegen (debounce): staat er voor dezelfde medewerker + datum al een
wachtende taak, dan schuiven we die een paar seconden op in plaats van een
nieuwe toe te voegen. Tien snelle wijzigingen leveren zo één API-call op.
Is de worker al met een taak bezig (status 'bezig'), dan komt er een nieuwe
taak bij: de wijziging mag niet verloren gaan. Tijden (niet_voor) zijn in UTC.
"""

import json
from datetime import date, timedelta

from ..extensions import db
from ..models import Dienst, Dienstcode, Medewerker, SyncTaak
from . import klok

DEBOUNCE_SECONDEN = 10


def _is_gekoppeld(medewerker: Medewerker | None) -> bool:
    return bool(medewerker and medewerker.agenda_modus and medewerker.agenda_id)


def plan_dag(medewerker: Medewerker, datum: date, commit: bool = True) -> None:
    """Plan een synchronisatie van één dag van één medewerker."""
    if not _is_gekoppeld(medewerker):
        return
    straks = klok.utc_nu() + timedelta(seconds=DEBOUNCE_SECONDEN)
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
                                niet_voor=klok.utc_nu()))
    db.session.commit()


def plan_code(code: Dienstcode) -> None:
    """Na het wijzigen van een dienstcode: toekomstige diensten met die code opnieuw zetten."""
    diensten = Dienst.query.filter(
        Dienst.dienstcode_id == code.id, Dienst.datum >= klok.vandaag()
    ).all()
    plan_diensten(diensten)


def plan_ontkoppel(medewerker: Medewerker, verwijder: bool) -> None:
    """Ontkoppel een medewerker. Met verwijder=True ruimt de worker de afspraken op
    (modus A: de hele agenda, modus B: alle afspraken van deze app).

    De koppeling zelf wordt direct losgemaakt; de afspraak-ID's in het rooster ook.
    """
    extra = {"agenda_id": medewerker.agenda_id, "modus": medewerker.agenda_modus,
             "verwijder": verwijder, "medewerker_id": medewerker.id}
    if medewerker.agenda_id and verwijder:
        db.session.add(SyncTaak(medewerker_id=medewerker.id, soort="ontkoppel",
                                niet_voor=klok.utc_nu(), extra=json.dumps(extra)))
    # Openstaande taken voor deze medewerker zijn niet meer nodig
    SyncTaak.query.filter(SyncTaak.medewerker_id == medewerker.id,
                          SyncTaak.soort != "ontkoppel", SyncTaak.status == "wacht").delete()
    for dienst in Dienst.query.filter(Dienst.medewerker_id == medewerker.id,
                                      Dienst.google_event_id != "").all():
        dienst.google_event_id = ""
        if dienst.is_leeg:
            db.session.delete(dienst)
    medewerker.agenda_modus = ""
    medewerker.agenda_id = ""
    medewerker.agenda_laatste_fout = ""
    medewerker.agenda_laatst_gesync = None
