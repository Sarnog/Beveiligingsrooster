"""Verwerking van de agenda-wachtrij (draait in de worker, nooit in een webverzoek).

Taaksoorten in 'sync_wachtrij':
    dag        één dag van één medewerker gelijk maken aan het rooster
    volledig   de hele periode (standaard vandaag -7 dagen t/m +12 maanden)
    ontkoppel  na het ontkoppelen: eventueel alle afspraken (of de agenda) verwijderen

Status van een taak: 'wacht' -> 'bezig' (de worker is ermee bezig) -> klaar (weg),
of terug naar 'wacht' (tijdelijke fout) of 'fout'. Komt er tijdens 'bezig' een nieuwe
wijziging binnen, dan maakt sync_planning een NIEUWE wachtende taak; de worker
verwijdert alleen de taak die hij zelf geclaimd had. Zo gaat er niets verloren.
Een taak die na een crash op 'bezig' blijft hangen, gaat na VASTGELOPEN terug naar 'wacht'.

Fouten: bij tijdelijke fouten (429, 5xx, netwerk) proberen we het later opnieuw,
steeds langer wachtend (exponentiële backoff: 30 s, 1 min, 2 min, ... max 1 uur).
Na MAX_POGINGEN, of bij een blijvende fout, krijgt de taak status 'fout' en komt
de melding in het logboek en bij de medewerker (Beheer -> Google Agenda).
Alle wachttijden (niet_voor) zijn in UTC (klok.utc_nu).
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
VASTGELOPEN = timedelta(minutes=10)  # zo lang mag een taak op 'bezig' staan


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


def _privé(afspraak: dict) -> dict:
    return afspraak.get("extendedProperties", {}).get("private", {})


def sync_volledig(klant, medewerker: Medewerker) -> int:
    """Maak de agenda gelijk aan het rooster in de sync-periode. Geeft het aantal afspraken.

    Alleen afspraken van DEZE medewerker worden aangeraakt (een gedeelde agenda kan ook
    afspraken van collega's bevatten). Oude afspraken zonder medewerker-markering tellen
    alleen mee als hun dienst van deze medewerker is.
    """
    van, tot = sync_periode()
    diensten = Dienst.query.filter(Dienst.medewerker_id == medewerker.id,
                                   Dienst.datum >= van, Dienst.datum <= tot).all()
    eigen_diensten = {str(d.id) for d in diensten}
    bestaande = {e["id"]: e for e in klant.eigen_afspraken(
        medewerker.agenda_id, van, tot, medewerker_id=medewerker.id)}
    for e in klant.eigen_afspraken(medewerker.agenda_id, van, tot):
        if not _privé(e).get("medewerker_id") and _privé(e).get("dienst_id") in eigen_diensten:
            bestaande[e["id"]] = e
    per_dienst = {_privé(e).get("dienst_id"): e["id"] for e in bestaande.values()}
    gebruikt: set[str] = set()
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


def ontkoppel(klant, extra: dict, medewerker_id: int | None = None) -> None:
    """Afspraken (modus B) of de hele agenda (modus A) verwijderen na het ontkoppelen.

    Modus B: alleen de afspraken van deze medewerker (de agenda kan gedeeld zijn).
    Het medewerker-ID staat in 'extra', want de medewerker kan al verwijderd zijn.
    """
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
        medewerker_id = extra.get("medewerker_id") or medewerker_id
        if not medewerker_id:
            log.warning("Ontkoppelen zonder medewerker-ID: afspraken blijven staan (%s)", agenda_id)
            return
        for afspraak in klant.eigen_afspraken(agenda_id, medewerker_id=medewerker_id):
            klant.verwijder_afspraak(agenda_id, afspraak["id"])


# ---------------------------------------------------------------------------
# De wachtrij
# ---------------------------------------------------------------------------

def _voer_uit(klant, taak: SyncTaak) -> None:
    if taak.soort == "ontkoppel":
        ontkoppel(klant, json.loads(taak.extra or "{}"), taak.medewerker_id)
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
    taak.laatste_fout = str(fout)[:1000]
    medewerker = db.session.get(Medewerker, taak.medewerker_id) if taak.medewerker_id else None
    if fout.tijdelijk and taak.pogingen < MAX_POGINGEN:
        taak.status = "wacht"
        taak.niet_voor = klok.utc_nu() + wachttijd(taak.pogingen)
        log.warning("Agenda-sync mislukt (poging %s), later opnieuw: %s", taak.pogingen, fout)
        return
    taak.status = "fout"
    if medewerker is not None:
        medewerker.agenda_laatste_fout = str(fout)
    logboek.log("Agenda-sync fout", str(fout),
                datum=taak.datum, medewerker=medewerker.naam if medewerker else "")
    log.error("Agenda-sync definitief mislukt: %s", fout)


def herstel_vastgelopen() -> int:
    """Taken die na een crash op 'bezig' zijn blijven staan weer in de wachtrij zetten."""
    nu = klok.utc_nu()
    aantal = SyncTaak.query.filter(
        SyncTaak.status == "bezig", SyncTaak.niet_voor < nu - VASTGELOPEN,
    ).update({"status": "wacht", "niet_voor": nu}, synchronize_session=False)
    db.session.commit()
    if aantal:
        log.warning("%s vastgelopen agenda-taken opnieuw in de wachtrij gezet", aantal)
    return aantal


def _claim(taak_id: int) -> SyncTaak | None:
    """Zet een wachtende taak op 'bezig' (niet_voor = starttijd) en sla dat direct op.

    Geeft de taak terug, of None als hij intussen niet meer wacht of weg is.
    """
    aantal = SyncTaak.query.filter_by(id=taak_id, status="wacht").update(
        {"status": "bezig", "niet_voor": klok.utc_nu()}, synchronize_session=False)
    db.session.commit()
    return db.session.get(SyncTaak, taak_id) if aantal == 1 else None


def verwerk_wachtrij(klant_maker=None) -> int:
    """Verwerk alle taken die aan de beurt zijn. Geeft het aantal verwerkte taken."""
    herstel_vastgelopen()
    taak_ids = [t.id for t in (
        SyncTaak.query.filter(SyncTaak.status == "wacht", SyncTaak.niet_voor <= klok.utc_nu())
        .order_by(SyncTaak.niet_voor, SyncTaak.id).limit(MAX_TAKEN_PER_RONDE).all()
    )]
    if not taak_ids:
        return 0
    try:
        klant = (klant_maker or google_agenda.klant)()
    except AgendaFout as fout:
        for taak in SyncTaak.query.filter(SyncTaak.id.in_(taak_ids)).all():
            _verwerk_fout(taak, fout)
        db.session.commit()
        return 0

    verwerkt = 0
    for taak_id in taak_ids:
        taak = _claim(taak_id)
        if taak is None:
            continue
        try:
            _voer_uit(klant, taak)
            # Alleen de eigen (geclaimde) taak weg; een nieuwe wachtende taak blijft staan
            SyncTaak.query.filter_by(id=taak_id).delete(synchronize_session=False)
            db.session.commit()
            verwerkt += 1
        except Exception as fout:  # één taak mag de wachtrij niet stilleggen
            db.session.rollback()
            if not isinstance(fout, AgendaFout):
                log.exception("Onverwachte fout bij agenda-taak %s", taak_id)
                fout = AgendaFout(f"Onverwachte fout: {fout}", tijdelijk=True)
            taak = db.session.get(SyncTaak, taak_id)  # na de rollback opnieuw ophalen
            if taak is None:
                continue  # intussen verwijderd
            _verwerk_fout(taak, fout)
            db.session.commit()
    return verwerkt


def probeer_mislukte_opnieuw() -> int:
    """Zet alle mislukte taken terug in de wachtrij."""
    aantal = SyncTaak.query.filter_by(status="fout").update(
        {"status": "wacht", "pogingen": 0, "niet_voor": klok.utc_nu()})
    db.session.commit()
    return aantal
