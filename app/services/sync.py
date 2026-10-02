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

Tempo: de klant wacht TUSSENPOZE (1 s) tussen twee Google-aanroepen, en een volledige sync
slaat ongewijzigde afspraken over (vingerafdruk 'inhoud'). Meldt Google toch een limiet
(quotaExceeded, rateLimitExceeded, 429), dan pauzeert de HELE wachtrij QUOTA_PAUZE lang:
alle modus A-agenda's horen bij hetzelfde service-account en delen dus dezelfde limiet.
Zo'n taak gaat terug naar 'wacht' en telt niet als mislukte poging.

Fouten: bij andere tijdelijke fouten (5xx, netwerk) proberen we het later opnieuw,
steeds langer wachtend (exponentiële backoff: 30 s, 1 min, 2 min, ... max 1 uur).
Na MAX_POGINGEN, of bij een blijvende fout, krijgt de taak status 'fout' en komt
de melding in het logboek en bij de medewerker (Beheer -> Google Agenda).
Alle wachttijden (niet_voor) zijn in UTC (klok.utc_nu).
"""

import base64
import hashlib
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm.attributes import set_committed_value

from ..extensions import db
from ..models import Dienst, Medewerker, SyncTaak
from . import google_agenda, instellingen, klok, logboek
from .google_agenda import BRON, AgendaFout, afspraak_voor, dagtekst_voor

log = logging.getLogger(__name__)
MAX_POGINGEN = 6
MAX_TAKEN_PER_RONDE = 50
VASTGELOPEN = timedelta(minutes=30)  # zo lang mag een taak op 'bezig' staan (jaar = ~6 min)
QUOTA_PAUZE = timedelta(minutes=30)  # wachtrij stil na een Google-limiet


def wachttijd(pogingen: int) -> timedelta:
    """Exponentiële backoff: 30 s, 60 s, 120 s, ... maximaal 1 uur."""
    return timedelta(seconds=min(30 * 2 ** max(pogingen - 1, 0), 3600))


def pauze_tot() -> datetime | None:
    """Tot wanneer (UTC) de wachtrij stilstaat na een Google-limiet, of None."""
    try:
        tot = datetime.fromisoformat(instellingen.lees("agenda_pauze_tot"))
    except ValueError:
        return None
    return tot if tot > klok.utc_nu() else None


def sync_periode() -> tuple[date, date]:
    vandaag = klok.vandaag()
    terug = instellingen.lees_int("agenda_sync_dagen_terug", 7)
    vooruit = instellingen.lees_int("agenda_sync_maanden_vooruit", 12)
    return vandaag - timedelta(days=terug), vandaag + timedelta(days=31 * vooruit)


# ---------------------------------------------------------------------------
# Losse acties
# ---------------------------------------------------------------------------

def event_id_voor(dienst: Dienst) -> str:
    """Vaste Google-event-ID van een dienst: altijd dezelfde voor medewerker + dag + volgnummer.

    Zo is aanmaken idempotent: mislukt een sync halverwege (of gaat het antwoord van Google
    verloren), dan maakt de volgende poging geen tweede afspraak maar vindt hij de eerste
    terug (Google antwoordt 409 'bestaat al'). Google eist base32hex (0-9, a-v), 5-1024 tekens.
    """
    sleutel = f"{BRON}|{dienst.medewerker_id}|{dienst.datum.isoformat()}|{dienst.volgnummer or 1}"
    code = base64.b32hexencode(hashlib.sha256(sleutel.encode()).digest()).decode()
    return "br" + code.rstrip("=").lower()


def _zet_afspraak(klant, agenda_id: str, dienst: Dienst, gewenst, bestaande_id: str) -> None:
    """Maak, wijzig of verwijder de afspraak van één dienst."""
    if gewenst is None:
        if bestaande_id:
            klant.verwijder_afspraak(agenda_id, bestaande_id)
        _bewaar_event_id(dienst, "")
        return
    if bestaande_id:
        try:
            _bewaar_event_id(dienst, klant.wijzig_afspraak(agenda_id, bestaande_id, gewenst.body))
            return
        except AgendaFout as fout:
            if fout.status not in (404, 410):
                raise
            # Afspraak is handmatig weggehaald: opnieuw aanmaken
    event_id = event_id_voor(dienst)
    try:
        _bewaar_event_id(dienst, klant.maak_afspraak(agenda_id, dict(gewenst.body, id=event_id)))
    except AgendaFout as fout:
        if fout.status != 409:
            raise
        # Bestaat al: aangemaakt bij een eerdere (half mislukte) poging, of ooit verwijderd
        # (Google bewaart het ID dan als geannuleerd). Bijwerken zet hem weer goed.
        _bewaar_event_id(dienst, klant.wijzig_afspraak(agenda_id, event_id, gewenst.body))


def _bewaar_event_id(dienst: Dienst, event_id: str) -> None:
    """Schrijf het event-ID alleen weg als de dienst sinds het lezen niet gewijzigd is.

    Een voorwaardelijke UPDATE ... WHERE versie = <gelezen versie>: heeft de planner de
    dienst intussen aangepast, dan staat er al een nieuwe taak klaar en overschrijft de
    worker niets. (Het vaste event-ID zorgt dat die taak de afspraak terugvindt.)
    """
    tabel = Dienst.__table__
    db.session.execute(tabel.update().where(tabel.c.id == dienst.id, tabel.c.versie == dienst.versie)
                       .values(google_event_id=event_id))
    set_committed_value(dienst, "google_event_id", event_id)


def _dagen_met_tweede_dienst(diensten: list[Dienst]) -> set[tuple[int, date]]:
    """(medewerker, datum) met een gevulde dienst 2: daar blijft een lege dienst 1 staan."""
    return {(d.medewerker_id, d.datum) for d in diensten if d.volgnummer == 2 and not d.is_leeg}


def _ruim_lege_dienst_op(dienst: Dienst, met_tweede: set[tuple[int, date]]) -> None:
    """Een lege regel die alleen nog bestond voor de agenda-afspraak mag nu weg.

    Behalve een lege dienst 1 naast een gevulde dienst 2 (zie weekrooster.ruim_dag_op).

    Voorwaardelijk (zelfde versie als bij het lezen, nog steeds zonder afspraak): heeft de
    planner de dag intussen opnieuw ingevuld, dan is de versie hoger en blijft de dienst staan.
    """
    if not dienst.is_leeg or dienst.google_event_id \
            or (dienst.volgnummer == 1 and (dienst.medewerker_id, dienst.datum) in met_tweede):
        return
    tabel = Dienst.__table__
    resultaat = db.session.execute(tabel.delete().where(
        tabel.c.id == dienst.id, tabel.c.versie == dienst.versie, tabel.c.google_event_id == ""))
    if resultaat.rowcount:
        db.session.expunge(dienst)


def sync_dag(klant, medewerker: Medewerker, datum: date) -> None:
    """Zet de afspraken van één dag goed: één afspraak per dienst (dus twee bij een 2e dienst).

    Geen dienst betekent ook geen afspraak (die houden we bij in de dienstregel).
    Buiten de sync-periode (zie sync_volledig) wordt niets aangemaakt of gewijzigd; daar
    worden alleen afspraken van gewiste diensten nog opgeruimd.
    """
    van, tot = sync_periode()
    binnen = van <= datum <= tot
    diensten = (Dienst.query.filter_by(medewerker_id=medewerker.id, datum=datum)
                .order_by(Dienst.volgnummer).all())
    dagtekst = dagtekst_voor(datum) if diensten and binnen else ""
    met_tweede = _dagen_met_tweede_dienst(diensten)
    for dienst in diensten:
        gewenst = afspraak_voor(dienst, dagtekst)
        if not binnen and gewenst is not None:
            continue  # buiten de periode: bestaande afspraak laten zoals hij is
        _zet_afspraak(klant, medewerker.agenda_id, dienst, gewenst, dienst.google_event_id)
        _ruim_lege_dienst_op(dienst, met_tweede)


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
    # Eén keer alle afspraken van de app ophalen en hier splitsen (scheelt Google-quota)
    bestaande = {}
    for e in klant.eigen_afspraken(medewerker.agenda_id, van, tot):
        eigenaar = _privé(e).get("medewerker_id")
        if eigenaar:
            van_hem = eigenaar == str(medewerker.id)
        else:  # oude afspraak zonder markering: herkennen aan de dienst
            van_hem = _privé(e).get("dienst_id") in eigen_diensten
        if van_hem:
            bestaande[e["id"]] = e
    per_dienst = {_privé(e).get("dienst_id"): e["id"] for e in bestaande.values()}
    gebruikt: set[str] = set()
    aantal = 0
    met_tweede = _dagen_met_tweede_dienst(diensten)
    for dienst in diensten:
        huidig = dienst.google_event_id if dienst.google_event_id in bestaande else ""
        huidig = huidig or per_dienst.get(str(dienst.id), "")
        gewenst = afspraak_voor(dienst, dagtekst_voor(dienst.datum))
        if gewenst is not None and huidig and _privé(bestaande[huidig]).get("inhoud") \
                == _privé(gewenst.body)["inhoud"]:
            if dienst.google_event_id != huidig:  # al goed bij Google: geen aanroep nodig
                _bewaar_event_id(dienst, huidig)
        else:
            _zet_afspraak(klant, medewerker.agenda_id, dienst, gewenst, huidig)
        if dienst.google_event_id:
            gebruikt.add(dienst.google_event_id)
            aantal += 1
        _ruim_lege_dienst_op(dienst, met_tweede)
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
    if fout.quota:  # Google-limiet: alles pauzeren, deze taak telt niet als mislukt
        tot = klok.utc_nu() + QUOTA_PAUZE
        instellingen.schrijf("agenda_pauze_tot", tot.isoformat())
        taak.status = "wacht"
        taak.niet_voor = tot
        taak.laatste_fout = str(fout)[:1000]
        minuten = int(QUOTA_PAUZE.total_seconds() // 60)
        logboek.log("Agenda-sync gepauzeerd", f"{fout} Pauze: {minuten} minuten.")
        log.warning("Google-limiet bereikt; agenda-wachtrij gepauzeerd tot %s (UTC)", tot)
        return
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
    if pauze_tot():
        return 0  # Google-limiet: even niets naar Google sturen
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
        log.debug("Agenda-taak %s gestart: %s, medewerker %s, datum %s, poging %s", taak_id,
                  taak.soort, taak.medewerker_id, taak.datum, taak.pogingen + 1)
        try:
            _voer_uit(klant, taak)
            # Alleen de eigen (geclaimde) taak weg; een nieuwe wachtende taak blijft staan
            SyncTaak.query.filter_by(id=taak_id).delete(synchronize_session=False)
            db.session.commit()
            verwerkt += 1
            log.debug("Agenda-taak %s klaar", taak_id)
        except Exception as fout:  # één taak mag de wachtrij niet stilleggen
            db.session.rollback()
            if not isinstance(fout, AgendaFout):
                log.exception("Onverwachte fout bij agenda-taak %s", taak_id)
                fout = AgendaFout(f"Onverwachte fout: {fout}", tijdelijk=True)
            taak = db.session.get(SyncTaak, taak_id)  # na de rollback opnieuw ophalen
            if taak is None:
                log.debug("Agenda-taak %s is intussen verwijderd", taak_id)
                continue  # intussen verwijderd
            _verwerk_fout(taak, fout)
            db.session.commit()
            if fout.quota:
                break  # de rest van de ronde wacht tot na de pauze
    return verwerkt


def probeer_mislukte_opnieuw() -> int:
    """Zet alle mislukte taken terug in de wachtrij en hef een Google-pauze op."""
    nu = klok.utc_nu()
    aantal = SyncTaak.query.filter_by(status="fout").update(
        {"status": "wacht", "pogingen": 0, "niet_voor": nu})
    if pauze_tot():  # taken die op het einde van de pauze wachten: nu meteen
        SyncTaak.query.filter(SyncTaak.status == "wacht", SyncTaak.niet_voor > nu).update(
            {"niet_voor": nu}, synchronize_session=False)
        instellingen.schrijf("agenda_pauze_tot", "")
    db.session.commit()
    return aantal
