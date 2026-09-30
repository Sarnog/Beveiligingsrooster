"""Verwerking van de agenda-wachtrij (draait in de worker, nooit in een webverzoek).

Taaksoorten in 'sync_wachtrij':
    dag        één dag van één medewerker gelijk maken aan het rooster
    volledig   de hele periode (standaard vandaag -7 dagen t/m +12 maanden)
    ontkoppel  na het ontkoppelen: eventueel alle afspraken (of de agenda) verwijderen

Fouten: bij tijdelijke fouten (429, 5xx, netwerk) proberen we het later opnieuw,
steeds langer wachtend (exponentiële backoff: 30 s, 1 min, 2 min, ... max 1 uur).
Na MAX_POGINGEN, of bij een blijvende fout, krijgt de taak status 'fout' en komt
de melding in het logboek en bij de medewerker (Beheer -> Google Agenda).
"""

import json
import logging
from datetime import date, timedelta

from ..extensions import db
from ..models import Dienst, Medewerker, SyncTaak
from . import google_agenda, instellingen, klok, logboek
from .google_agenda import AgendaFout, afspraak_voor, dagtekst_voor

log = logging.getLogger(__name__)
MAX_POGINGEN = 6
MAX_TAKEN_PER_RONDE = 50


def wachttijd(pogingen: int) -> timedelta:
    """Exponentiële backoff: 30 s, 60 s, 120 s, ... maximaal 1 uur."""
    return timedelta(seconds=min(30 * 2 ** max(pogingen - 1, 0), 3600))


def sync_periode() -> tuple[date, date]:
    vandaag = klok.vandaag()
    terug = instellingen.lees_int("agenda_sync_dagen_terug", 7)
    vooruit = instellingen.lees_int("agenda_sync_maanden_vooruit", 12)
    return vandaag - timedelta(days=terug), vandaag + timedelta(days=31 * vooruit)


# ---------------------------------------------------------------------------
# Losse acties
# ---------------------------------------------------------------------------

def _zet_afspraak(klant, agenda_id: str, dienst: Dienst, gewenst, bestaande_id: str) -> None:
    """Maak, wijzig of verwijder de afspraak van één dienst."""
    if gewenst is None:
        if bestaande_id:
            klant.verwijder_afspraak(agenda_id, bestaande_id)
        dienst.google_event_id = ""
        return
    if bestaande_id:
        try:
            dienst.google_event_id = klant.wijzig_afspraak(agenda_id, bestaande_id, gewenst.body)
            return
        except AgendaFout as fout:
            if fout.status not in (404, 410):
                raise
            # Afspraak is handmatig weggehaald: opnieuw aanmaken
    dienst.google_event_id = klant.maak_afspraak(agenda_id, gewenst.body)


def _ruim_lege_dienst_op(dienst: Dienst) -> None:
    """Een lege regel die alleen nog bestond voor de agenda-afspraak mag nu weg."""
    if dienst.is_leeg and not dienst.google_event_id:
        db.session.delete(dienst)


def sync_dag(klant, medewerker: Medewerker, datum: date) -> None:
    dienst = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=datum).first()
    if dienst is None:
        return  # geen dienst en ook geen afspraak (die houden we bij in de dienstregel)
    gewenst = afspraak_voor(dienst, dagtekst_voor(datum))
    _zet_afspraak(klant, medewerker.agenda_id, dienst, gewenst, dienst.google_event_id)
    _ruim_lege_dienst_op(dienst)


def sync_volledig(klant, medewerker: Medewerker) -> int:
    """Maak de agenda gelijk aan het rooster in de sync-periode. Geeft het aantal afspraken."""
    van, tot = sync_periode()
    bestaande = {e["id"]: e for e in klant.eigen_afspraken(medewerker.agenda_id, van, tot)}
    per_dienst = {
        e.get("extendedProperties", {}).get("private", {}).get("dienst_id"): e["id"]
        for e in bestaande.values()
    }
    gebruikt: set[str] = set()
    diensten = Dienst.query.filter(Dienst.medewerker_id == medewerker.id,
                                   Dienst.datum >= van, Dienst.datum <= tot).all()
    aantal = 0
    for dienst in diensten:
        huidig = dienst.google_event_id if dienst.google_event_id in bestaande else ""
        huidig = huidig or per_dienst.get(str(dienst.id), "")
        gewenst = afspraak_voor(dienst, dagtekst_voor(dienst.datum))
        _zet_afspraak(klant, medewerker.agenda_id, dienst, gewenst, huidig)
        if dienst.google_event_id:
            gebruikt.add(dienst.google_event_id)
            aantal += 1
        _ruim_lege_dienst_op(dienst)
    # 'Wezen': afspraken van deze app zonder bijbehorende dienst
    for event_id in bestaande:
        if event_id not in gebruikt:
            klant.verwijder_afspraak(medewerker.agenda_id, event_id)
    return aantal


def ontkoppel(klant, extra: dict) -> None:
    """Afspraken (modus B) of de hele agenda (modus A) verwijderen na het ontkoppelen."""
    if not extra.get("verwijder"):
        return
    agenda_id = extra.get("agenda_id", "")
    if not agenda_id:
        return
    if extra.get("modus") == "A":
        try:
            klant.verwijder_agenda(agenda_id)
        except AgendaFout as fout:
            if fout.status not in (404, 410):
                raise
    else:
        for afspraak in klant.eigen_afspraken(agenda_id):
            klant.verwijder_afspraak(agenda_id, afspraak["id"])


# ---------------------------------------------------------------------------
# De wachtrij
# ---------------------------------------------------------------------------

def _voer_uit(klant, taak: SyncTaak) -> None:
    if taak.soort == "ontkoppel":
        ontkoppel(klant, json.loads(taak.extra or "{}"))
        return
    medewerker = db.session.get(Medewerker, taak.medewerker_id) if taak.medewerker_id else None
    if medewerker is None or not (medewerker.agenda_modus and medewerker.agenda_id):
        return  # inmiddels ontkoppeld: niets te doen
    if taak.soort == "volledig":
        aantal = sync_volledig(klant, medewerker)
        logboek.log("Agenda gesynchroniseerd", f"Volledig: {aantal} afspraken",
                    medewerker=medewerker.naam)
    else:
        sync_dag(klant, medewerker, taak.datum)
    medewerker.agenda_laatst_gesync = klok.nu()
    medewerker.agenda_laatste_fout = ""


def _verwerk_fout(taak: SyncTaak, fout: AgendaFout) -> None:
    taak.pogingen += 1
    taak.laatste_fout = str(fout)
    medewerker = db.session.get(Medewerker, taak.medewerker_id) if taak.medewerker_id else None
    if fout.tijdelijk and taak.pogingen < MAX_POGINGEN:
        taak.niet_voor = klok.nu() + wachttijd(taak.pogingen)
        log.warning("Agenda-sync mislukt (poging %s), later opnieuw: %s", taak.pogingen, fout)
        return
    taak.status = "fout"
    if medewerker is not None:
        medewerker.agenda_laatste_fout = str(fout)
    logboek.log("Agenda-sync fout", str(fout),
                datum=taak.datum, medewerker=medewerker.naam if medewerker else "")
    log.error("Agenda-sync definitief mislukt: %s", fout)


def verwerk_wachtrij(klant_maker=None) -> int:
    """Verwerk alle taken die aan de beurt zijn. Geeft het aantal verwerkte taken."""
    taken = (
        SyncTaak.query.filter(SyncTaak.status == "wacht", SyncTaak.niet_voor <= klok.nu())
        .order_by(SyncTaak.niet_voor, SyncTaak.id).limit(MAX_TAKEN_PER_RONDE).all()
    )
    if not taken:
        return 0
    try:
        klant = (klant_maker or google_agenda.klant)()
    except AgendaFout as fout:
        for taak in taken:
            _verwerk_fout(taak, fout)
        db.session.commit()
        return 0

    verwerkt = 0
    for taak in taken:
        try:
            _voer_uit(klant, taak)
            db.session.delete(taak)
            db.session.commit()
            verwerkt += 1
        except AgendaFout as fout:
            db.session.rollback()
            taak = db.session.get(SyncTaak, taak.id)
            _verwerk_fout(taak, fout)
            db.session.commit()
    return verwerkt


def probeer_mislukte_opnieuw() -> int:
    """Zet alle mislukte taken terug in de wachtrij."""
    aantal = SyncTaak.query.filter_by(status="fout").update(
        {"status": "wacht", "pogingen": 0, "niet_voor": klok.nu()})
    db.session.commit()
    return aantal
