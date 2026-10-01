"""Google Agenda-synchronisatie (met een nep-Google) en de ICS-feed (fase 3)."""

import io
import json
import os
import stat
from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import Dienst, Dienstcode, Logboek, Medewerker, SyncTaak
from app.services import google_agenda, sync
from app.services.google_agenda import AgendaFout, afspraak_voor
from app.services.urenberekening import bereken_uren
from app.services.voorbeeldpakket import laad_voorbeeldpakket
from app.services.weekrooster import Wijziging, wijzig_cellen

MAANDAG = date(2026, 3, 2)


class NepKlant:
    """Doet alsof het Google Calendar is (alles in het geheugen)."""

    def __init__(self):
        self.agendas: dict[str, dict] = {}
        self.teller = 0
        self.gedeeld: list[tuple[str, str]] = []
        # Tijdelijke fout (503) bij de n-de aanroep van een methode: {"maak_afspraak": {2}}
        self.faal_bij: dict[str, set[int]] = {}
        self.aanroepen: dict[str, int] = {}
        # Verwijderde afspraken houden bij Google hun ID ('cancelled'): opnieuw invoegen geeft 409
        self.verwijderd: dict[str, dict] = {}

    def _tel(self, methode):
        self.aanroepen[methode] = self.aanroepen.get(methode, 0) + 1
        if self.aanroepen[methode] in self.faal_bij.get(methode, set()):
            raise AgendaFout("Google even weg (503)", tijdelijk=True, status=503)

    def _nieuw_id(self, soort):
        self.teller += 1
        return f"{soort}{self.teller}"

    def maak_agenda(self, titel, tijdzone):
        agenda_id = self._nieuw_id("agenda") + "@group.calendar.google.com"
        self.agendas[agenda_id] = {}
        return agenda_id

    def deel_agenda(self, agenda_id, email):
        self.gedeeld.append((agenda_id, email))

    def agenda_info(self, agenda_id):
        if agenda_id not in self.agendas:
            raise AgendaFout("niet gevonden", status=404)
        return {"summary": "Test"}

    def verwijder_agenda(self, agenda_id):
        self.agendas.pop(agenda_id, None)

    def maak_afspraak(self, agenda_id, body):
        self._tel("maak_afspraak")
        event_id = body.get("id") or self._nieuw_id("event")
        if event_id in self.agendas.get(agenda_id, {}) or event_id in self.verwijderd:
            raise AgendaFout("Afspraak bestaat al (409)", status=409)
        self.agendas.setdefault(agenda_id, {})[event_id] = dict(body, id=event_id)
        return event_id

    def wijzig_afspraak(self, agenda_id, event_id, body):
        self._tel("wijzig_afspraak")
        if event_id in self.verwijderd:  # een geannuleerde afspraak wordt weer actief
            self.agendas.setdefault(agenda_id, {})[event_id] = self.verwijderd.pop(event_id)
        if event_id not in self.agendas.get(agenda_id, {}):
            raise AgendaFout("niet gevonden", status=404)
        self.agendas[agenda_id][event_id] = dict(body, id=event_id)
        return event_id

    def verwijder_afspraak(self, agenda_id, event_id):
        self._tel("verwijder_afspraak")
        weg = self.agendas.get(agenda_id, {}).pop(event_id, None)
        if weg is not None:
            self.verwijderd[event_id] = weg

    def eigen_afspraken(self, agenda_id, van=None, tot=None, medewerker_id=None):
        """Zelfde filters als Google: bron=beveiligingsrooster (en eventueel medewerker_id)."""
        resultaat = []
        for e in self.agendas.get(agenda_id, {}).values():
            privé = e.get("extendedProperties", {}).get("private", {})
            if privé.get("bron") != "beveiligingsrooster":
                continue
            if medewerker_id is not None and privé.get("medewerker_id") != str(medewerker_id):
                continue
            resultaat.append(e)
        return resultaat


@pytest.fixture
def nep(app, monkeypatch):
    klant = NepKlant()
    klant.agendas["agenda-a"] = {}
    monkeypatch.setattr(google_agenda, "klant", lambda: klant)
    return klant


@pytest.fixture
def gekoppeld(klaar, nep):
    from app.services import instellingen

    laad_voorbeeldpakket()
    # De tests gebruiken vaste datums (maart 2026); sinds 1.5.0 synchroniseert sync_dag alleen
    # binnen de sync-periode (audit L6). Daarom hier een ruime periode terug.
    instellingen.schrijf("agenda_sync_dagen_terug", "3650")
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA", email="a@voorbeeld.nl",
                            agenda_modus="B", agenda_id="agenda-a")
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def wachtrij_nu_uitvoeren():
    """Debounce overslaan: alle wachtende taken direct aan de beurt."""
    SyncTaak.query.update({"niet_voor": datetime(2000, 1, 1)})
    db.session.commit()
    return sync.verwerk_wachtrij()


def afspraken(nep, agenda="agenda-a"):
    return list(nep.agendas.get(agenda, {}).values())


# ---------- Afspraak opbouwen ----------

def test_afspraak_met_tijden(app, gekoppeld):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4"),
                   Wijziging(gekoppeld.id, MAANDAG, "opmerking", "BHV")])
    dienst = Dienst.query.one()
    body = afspraak_voor(dienst, "Voorjaarsvakantie").body
    assert body["summary"] == "VW Vroeg"
    assert body["start"] == {"dateTime": "2026-03-02T07:15:00", "timeZone": "Europe/Amsterdam"}
    assert body["end"]["dateTime"] == "2026-03-02T15:45:00"
    assert "Dienstcode: 4" in body["description"] and "Opmerking: BHV" in body["description"]
    assert "Dag: Voorjaarsvakantie" in body["description"]
    assert "niet handmatig wijzigen" in body["description"]
    assert body["extendedProperties"]["private"]["bron"] == "beveiligingsrooster"


def test_nachtdienst_in_de_nacht_van_de_klokwissel(app, gekoppeld):
    # Zaterdag 24-10-2026 -> zondag 25-10-2026: de klok gaat om 03:00 terug naar 02:00
    zaterdag = date(2026, 10, 24)
    wijzig_cellen([Wijziging(gekoppeld.id, zaterdag, "begin", "22:00"),
                   Wijziging(gekoppeld.id, zaterdag, "eind", "06:30")])
    dienst = Dienst.query.one()
    dienst.dienstnaam_override = "Nachtdienst"
    body = afspraak_voor(dienst).body
    assert body["start"]["dateTime"] == "2026-10-24T22:00:00"
    assert body["end"]["dateTime"] == "2026-10-25T06:30:00"  # volgende dag, Google regelt de DST
    # Uren volgen bewust de Excel-logica (wandklok): 8,5 - 0,5 = 8,0 x 1,5 (zaterdag)
    assert bereken_uren("22:00", "06:30", 1.5) == 12.0


def test_hele_dag_en_niet_in_agenda(app, gekoppeld):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "10")])  # Bapo, geen tijden
    body = afspraak_voor(Dienst.query.one()).body
    assert body["start"] == {"date": "2026-03-02"} and body["end"] == {"date": "2026-03-03"}
    code = Dienstcode.query.filter_by(nummer=10).one()
    code.in_agenda = False
    db.session.commit()
    assert afspraak_voor(Dienst.query.one()) is None


def test_voorvoegsel(app, gekoppeld):
    from app.services import instellingen

    instellingen.schrijf("agenda_voorvoegsel", "Werk: ")
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    assert afspraak_voor(Dienst.query.one()).body["summary"] == "Werk: VW Vroeg"


# ---------- Wachtrij en synchronisatie ----------

def test_wijziging_komt_via_wachtrij_in_agenda(app, gekoppeld, nep):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    taak = SyncTaak.query.one()
    assert taak.niet_voor > datetime.now() - timedelta(minutes=5)  # debounce: nog even wachten
    assert wachtrij_nu_uitvoeren() == 1
    assert SyncTaak.query.count() == 0
    assert [a["summary"] for a in afspraken(nep)] == ["VW Vroeg"]
    assert Dienst.query.one().google_event_id
    assert db.session.get(Medewerker, gekoppeld.id).agenda_laatst_gesync is not None


def test_tien_snelle_wijzigingen_een_taak(app, gekoppeld, nep):
    for code in ["4", "5", "4", "5", "4", "5", "4", "5", "4", "7"]:
        wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", code)])
    assert SyncTaak.query.count() == 1
    wachtrij_nu_uitvoeren()
    assert [a["summary"] for a in afspraken(nep)] == ["OB Vroeg"]


def test_dienst_wissen_verwijdert_afspraak(app, gekoppeld, nep):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    wachtrij_nu_uitvoeren()
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "15")])  # blanco-code
    # De lege regel blijft even bestaan zolang de afspraak nog weg moet
    assert Dienst.query.count() == 1
    wachtrij_nu_uitvoeren()
    assert afspraken(nep) == [] and Dienst.query.count() == 0


def test_handmatig_verwijderde_afspraak_wordt_opnieuw_gemaakt(app, gekoppeld, nep):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    wachtrij_nu_uitvoeren()
    nep.agendas["agenda-a"].clear()  # iemand verwijdert hem in Google
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "eind", "16:00")])
    wachtrij_nu_uitvoeren()
    assert afspraken(nep)[0]["end"]["dateTime"].endswith("16:00:00")


def test_volledige_sync_ruimt_wezen_op(app, gekoppeld, nep):
    # Een oude afspraak van de app zonder dienst ('wees') en een afspraak van de collega zelf
    nep.agendas["agenda-a"]["wees"] = {"id": "wees", "start": {"date": "2026-03-03"},
                                       "extendedProperties": {"private": {
                                           "bron": "beveiligingsrooster", "dienst_id": "999",
                                           "medewerker_id": str(gekoppeld.id)}}}
    nep.agendas["agenda-a"]["eigen"] = {"id": "eigen", "summary": "Tandarts"}
    vandaag = date.today()
    db.session.add(Dienst(medewerker_id=gekoppeld.id, datum=vandaag + timedelta(days=3),
                          dienstcode_id=Dienstcode.query.filter_by(nummer=4).one().id,
                          begin="07:15", eind="15:45", dienstnaam_override="", opmerking_tekst=""))
    db.session.commit()
    from app.services import sync_planning

    sync_planning.plan_volledig(gekoppeld)
    wachtrij_nu_uitvoeren()
    ids = set(nep.agendas["agenda-a"])
    assert "wees" not in ids and "eigen" in ids  # alleen eigen afspraken worden aangeraakt
    assert len(ids) == 2
    assert Logboek.query.filter_by(actie="Agenda gesynchroniseerd").count() == 1


def test_tijdelijke_fout_backoff_en_definitieve_fout(app, gekoppeld, monkeypatch):
    class KapotteKlant(NepKlant):
        def maak_afspraak(self, agenda_id, body):
            raise AgendaFout("Te veel verzoeken (429)", tijdelijk=True, status=429)

    kapot = KapotteKlant()
    monkeypatch.setattr(google_agenda, "klant", lambda: kapot)
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    wachtrij_nu_uitvoeren()
    taak = SyncTaak.query.one()
    assert taak.pogingen == 1 and taak.status == "wacht" and taak.niet_voor > datetime.now()
    for _ in range(sync.MAX_POGINGEN):
        wachtrij_nu_uitvoeren()
    taak = SyncTaak.query.one()
    assert taak.status == "fout"
    assert "429" in db.session.get(Medewerker, gekoppeld.id).agenda_laatste_fout
    assert Logboek.query.filter_by(actie="Agenda-sync fout").count() == 1
    # Opnieuw proberen zet de taak terug
    assert sync.probeer_mislukte_opnieuw() == 1


def test_wachttijd_groeit_exponentieel():
    assert [sync.wachttijd(p).seconds for p in (1, 2, 3, 4)] == [30, 60, 120, 240]
    assert sync.wachttijd(20).seconds == 3600


def test_naamwijziging_code_plant_hersync(app, gekoppeld, als_beheerder):
    toekomst = date.today() + timedelta(days=2)
    wijzig_cellen([Wijziging(gekoppeld.id, toekomst, "code", "4")])
    wachtrij_nu_uitvoeren()
    code = Dienstcode.query.filter_by(nummer=4).one()
    als_beheerder.post(f"/beheer/dienstcodes/{code.id}", data={
        "nummer": "4", "omschrijving": "VW Vroeg (nieuw)", "std_begin": "07:15", "std_eind": "15:45",
        "vet": "1", "actief": "1", "in_agenda": "1"})
    assert SyncTaak.query.count() == 1


# ---------- Beheerscherm ----------

def test_ontkoppelen_modus_a_verwijdert_agenda(app, gekoppeld, nep, als_beheerder):
    medewerker = db.session.get(Medewerker, gekoppeld.id)
    medewerker.agenda_modus, medewerker.agenda_id = "", ""
    db.session.commit()
    als_beheerder.post(f"/beheer/agenda/{medewerker.id}/koppel", data={"modus": "A"})
    medewerker = db.session.get(Medewerker, medewerker.id)
    assert medewerker.agenda_modus == "A" and medewerker.agenda_id in nep.agendas
    assert nep.gedeeld == [(medewerker.agenda_id, "a@voorbeeld.nl")]
    agenda_id = medewerker.agenda_id
    als_beheerder.post(f"/beheer/agenda/{medewerker.id}/ontkoppel", data={"verwijder": "1"})
    assert db.session.get(Medewerker, medewerker.id).agenda_modus == ""
    wachtrij_nu_uitvoeren()
    assert agenda_id not in nep.agendas


def test_koppelen_modus_b_test_agenda(app, gekoppeld, nep, als_beheerder):
    medewerker = db.session.get(Medewerker, gekoppeld.id)
    medewerker.agenda_modus, medewerker.agenda_id = "", ""
    db.session.commit()
    antwoord = als_beheerder.post(f"/beheer/agenda/{gekoppeld.id}/koppel",
                                  data={"modus": "B", "agenda_id": "bestaat-niet"}, follow_redirects=True)
    assert "Koppelen mislukt" in antwoord.data.decode()


def test_medewerker_verwijderen_met_agenda(app, gekoppeld, nep, als_beheerder):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    wachtrij_nu_uitvoeren()
    als_beheerder.post(f"/beheer/medewerkers/{gekoppeld.id}/verwijder",
                       data={"bevestig": "1", "agenda": "verwijderen"})
    assert Medewerker.query.count() == 0
    taak = SyncTaak.query.one()
    assert taak.medewerker_id is None and taak.soort == "ontkoppel"
    wachtrij_nu_uitvoeren()
    assert afspraken(nep) == []


def test_sleutel_uploaden(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/agenda/sleutel", data={
        "sleutel": (io.BytesIO(b'{"type": "iets anders"}'), "sleutel.json")},
        content_type="multipart/form-data", follow_redirects=True)
    assert "geen sleutelbestand" in antwoord.data.decode()
    geldig = json.dumps({"type": "service_account", "client_email": "rooster@project.iam.gserviceaccount.com",
                         "private_key": "-----BEGIN PRIVATE KEY-----\\nXX\\n-----END PRIVATE KEY-----\\n"})
    antwoord = als_beheerder.post("/beheer/agenda/sleutel", data={
        "sleutel": (io.BytesIO(geldig.encode()), "sleutel.json")},
        content_type="multipart/form-data", follow_redirects=True)
    pagina = antwoord.data.decode()
    assert "rooster@project.iam.gserviceaccount.com" in pagina
    rechten = stat.S_IMODE(os.stat(google_agenda.sleutel_pad()).st_mode)
    assert rechten == 0o600


def test_agenda_scherm(als_beheerder, gekoppeld):
    assert als_beheerder.get("/beheer/agenda").status_code == 200


# ---------- ICS ----------

def test_ics_feed(app, client, gekoppeld, als_beheerder):
    vandaag = date.today()
    wijzig_cellen([Wijziging(gekoppeld.id, vandaag, "code", "4")])
    als_beheerder.post(f"/beheer/agenda/{gekoppeld.id}/ics")
    token = db.session.get(Medewerker, gekoppeld.id).ics_token
    assert len(token) > 20
    als_beheerder.post("/uitloggen")
    antwoord = client.get(f"/ics/{token}.ics")  # zonder login
    assert antwoord.status_code == 200 and antwoord.mimetype == "text/calendar"
    tekst = antwoord.data.decode()
    assert tekst.startswith("BEGIN:VCALENDAR\r\n") and "SUMMARY:VW Vroeg" in tekst
    assert f"DTSTART:{vandaag.strftime('%Y%m%d')}T" in tekst and "Z\r\n" in tekst
    assert client.get("/ics/verkeerd-token-van-voldoende-lengte.ics").status_code == 404


def test_ics_tijden_in_utc_met_zomertijd(app, gekoppeld):
    from app.services.ics import _utc

    assert _utc("2026-03-02T07:15:00") == "20260302T061500Z"  # wintertijd (UTC+1)
    assert _utc("2026-07-01T07:15:00") == "20260701T051500Z"  # zomertijd (UTC+2)


def test_migraties_kloppen_met_model(tmp_path, monkeypatch):
    """Een lege database met 'flask db upgrade' moet precies het datamodel opleveren."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from flask_migrate import upgrade

    from app import create_app

    from .conftest import TestConfig

    app = create_app(TestConfig(str(tmp_path)))
    with app.app_context():
        upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
        with db.engine.connect() as verbinding:
            verschillen = compare_metadata(MigrationContext.configure(verbinding), db.metadata)
        assert verschillen == []


# ---------- Modus A koppelen (knop mag nooit 'stil' niets doen) ----------

def test_modus_a_met_email_in_het_formulier(app, klaar, nep, als_beheerder, monkeypatch):
    monkeypatch.setattr(google_agenda, "sleutel_aanwezig", lambda: True)
    # Na een Excel-import hebben medewerkers nog geen e-mailadres
    medewerker = Medewerker(naam="Medewerker Z", initialen="TSZ")
    db.session.add(medewerker)
    db.session.commit()
    pagina = als_beheerder.get("/beheer/agenda").data.decode()
    formulier = pagina.split('name="modus" value="A"')[1].split("</form>")[0]
    assert 'name="email"' in formulier and "disabled" not in formulier
    antwoord = als_beheerder.post(f"/beheer/agenda/{medewerker.id}/koppel",
                                  data={"modus": "A", "email": "z@voorbeeld.nl"}, follow_redirects=True)
    assert "is gekoppeld" in antwoord.data.decode()
    medewerker = db.session.get(Medewerker, medewerker.id)
    assert medewerker.email == "z@voorbeeld.nl" and medewerker.agenda_modus == "A"
    assert nep.gedeeld == [(medewerker.agenda_id, "z@voorbeeld.nl")]


def test_modus_a_zonder_email_geeft_duidelijke_melding(app, klaar, nep, als_beheerder):
    medewerker = Medewerker(naam="Medewerker Z", initialen="TSZ")
    db.session.add(medewerker)
    db.session.commit()
    antwoord = als_beheerder.post(f"/beheer/agenda/{medewerker.id}/koppel",
                                  data={"modus": "A", "email": ""}, follow_redirects=True)
    assert "Vul een geldig e-mailadres" in antwoord.data.decode()
    assert db.session.get(Medewerker, medewerker.id).agenda_modus == ""


def test_modus_a_delen_mislukt_ruimt_agenda_op(app, klaar, monkeypatch, als_beheerder):
    class DelenMislukt(NepKlant):
        def deel_agenda(self, agenda_id, email):
            raise AgendaFout("Geen toegang (403)", status=403)

    klant = DelenMislukt()
    monkeypatch.setattr(google_agenda, "klant", lambda: klant)
    medewerker = Medewerker(naam="Medewerker Z", initialen="TSZ", email="z@voorbeeld.nl")
    db.session.add(medewerker)
    db.session.commit()
    antwoord = als_beheerder.post(f"/beheer/agenda/{medewerker.id}/koppel", data={"modus": "A"},
                                  follow_redirects=True)
    assert "Koppelen mislukt" in antwoord.data.decode()
    assert klant.agendas == {}  # geen losse agenda achtergelaten
    assert db.session.get(Medewerker, medewerker.id).agenda_modus == ""


def test_geweigerde_sleutel_geeft_duidelijke_melding():
    from google.auth.exceptions import RefreshError

    from app.services.google_agenda import _vertaal_fout

    fout = _vertaal_fout(RefreshError("invalid_grant: Invalid grant: account not found"))
    assert "weigert de sleutel" in str(fout) and not fout.tijdelijk


def test_klant_met_echte_bibliotheek(app, tmp_path):
    """De echte Google-klant kan gebouwd worden (zonder internet), met time-out."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    sleutel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = sleutel.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    google_agenda.bewaar_sleutel(json.dumps({
        "type": "service_account", "project_id": "test", "private_key_id": "x",
        "private_key": pem, "client_email": "rooster@test.iam.gserviceaccount.com",
        "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}).encode())
    klant = google_agenda.klant()
    assert isinstance(klant, google_agenda.AgendaKlant)
    assert klant.service._http.http.timeout == google_agenda.TIMEOUT


# ---------- Twee diensten op één dag (1.4.0) ----------

def test_twee_diensten_geven_twee_afspraken(app, gekoppeld, nep):
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "17/3")])
    assert SyncTaak.query.count() == 1  # één taak voor de dag
    wachtrij_nu_uitvoeren()
    assert sorted(a["summary"] for a in afspraken(nep)) == ["BHV", "VW Avond"]
    ids = {d.volgnummer: d.google_event_id for d in Dienst.query.all()}
    assert ids[1] and ids[2] and ids[1] != ids[2]  # eigen afspraak per dienst
    # Tweede dienst weg: alleen die afspraak verdwijnt
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "17")])
    wachtrij_nu_uitvoeren()
    assert [a["summary"] for a in afspraken(nep)] == ["BHV"]
    assert [d.volgnummer for d in Dienst.query.all()] == [1]


def test_ics_feed_met_twee_diensten(app, gekoppeld):
    from app.services.ics import maak_feed

    vandaag = date.today()
    wijzig_cellen([Wijziging(gekoppeld.id, vandaag, "code", "17/3")])
    tekst = maak_feed(db.session.get(Medewerker, gekoppeld.id))
    assert tekst.count("BEGIN:VEVENT") == 2
    assert tekst.index("SUMMARY:BHV") < tekst.index("SUMMARY:VW Avond")  # op volgorde
    uids = {d.id for d in Dienst.query.all()}
    for dienst_id in uids:
        assert f"UID:dienst-{dienst_id}@beveiligingsrooster" in tekst


def test_gewiste_tweede_dienst_met_afspraak_wordt_niet_meer_getoond(app, gekoppeld, nep):
    from app.services.weekrooster import week_gegevens

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "17/3")])
    wachtrij_nu_uitvoeren()
    bijgewerkt, _ = wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "17")])
    assert Dienst.query.count() == 2  # lege dienst 2 wacht nog op het weghalen van de afspraak
    assert bijgewerkt[f"{gekoppeld.id}|{MAANDAG.isoformat()}"]["code"] == "17"
    rij = week_gegevens(2026, 10)["rijen"][0]
    assert not rij.heeft_tweede and rij.dagen[0]["tweede"] is None


# ---------- Beheer → Google Agenda: overige knoppen en foutpaden ----------

def test_sleutel_verwijderen_en_leeg_formulier(app, als_beheerder, monkeypatch):
    weg = []
    monkeypatch.setattr(google_agenda, "verwijder_sleutel", lambda: weg.append(True))
    antwoord = als_beheerder.post("/beheer/agenda/sleutel", data={"verwijder": "1"}, follow_redirects=True)
    assert weg == [True] and "Het sleutelbestand is verwijderd" in antwoord.data.decode()
    assert Logboek.query.filter_by(actie="Google-sleutel verwijderd").count() == 1
    antwoord = als_beheerder.post("/beheer/agenda/sleutel", data={}, follow_redirects=True)
    assert "Kies een JSON-sleutelbestand" in antwoord.data.decode()


def test_koppelen_al_gekoppeld_onbekende_modus_en_leeg_agenda_id(app, gekoppeld, nep, als_beheerder):
    url = f"/beheer/agenda/{gekoppeld.id}/koppel"
    antwoord = als_beheerder.post(url, data={"modus": "B"}, follow_redirects=True)
    assert "is al gekoppeld" in antwoord.data.decode()
    medewerker = db.session.get(Medewerker, gekoppeld.id)
    medewerker.agenda_modus, medewerker.agenda_id = "", ""
    db.session.commit()
    antwoord = als_beheerder.post(url, data={"modus": "B", "agenda_id": " "}, follow_redirects=True)
    assert "Vul het agenda-ID in" in antwoord.data.decode()
    antwoord = als_beheerder.post(url, data={"modus": "X"}, follow_redirects=True)
    assert "Onbekende koppelmodus" in antwoord.data.decode()
    antwoord = als_beheerder.post(url, data={"modus": "B", "agenda_id": "agenda-a"}, follow_redirects=True)
    assert "is gekoppeld" in antwoord.data.decode() and "uitnodiging" not in antwoord.data.decode()
    assert db.session.get(Medewerker, gekoppeld.id).agenda_modus == "B"


def test_modus_a_opruimen_mislukt_ook(app, klaar, monkeypatch, als_beheerder):
    class AllesMislukt(NepKlant):
        def deel_agenda(self, agenda_id, email):
            raise AgendaFout("Geen toegang (403)", status=403)

        def verwijder_agenda(self, agenda_id):
            raise AgendaFout("Ook weg (500)", status=500)

    monkeypatch.setattr(google_agenda, "klant", lambda: AllesMislukt())
    medewerker = Medewerker(naam="Medewerker Z", initialen="TSZ", email="z@voorbeeld.nl")
    db.session.add(medewerker)
    db.session.commit()
    antwoord = als_beheerder.post(f"/beheer/agenda/{medewerker.id}/koppel", data={"modus": "A"},
                                  follow_redirects=True)
    assert "Koppelen mislukt: Geen toegang (403)" in antwoord.data.decode()


def test_koppeling_testen(app, gekoppeld, nep, als_beheerder):
    url = f"/beheer/agenda/{gekoppeld.id}/test"
    assert "Koppeling werkt: agenda" in als_beheerder.post(url, follow_redirects=True).data.decode()
    del nep.agendas["agenda-a"]
    assert "Koppeling werkt niet" in als_beheerder.post(url, follow_redirects=True).data.decode()
    assert db.session.get(Medewerker, gekoppeld.id).agenda_laatste_fout == "niet gevonden"


def test_volledig_synchroniseren_en_opnieuw_proberen(app, gekoppeld, nep, als_beheerder):
    antwoord = als_beheerder.post(f"/beheer/agenda/{gekoppeld.id}/volledig", follow_redirects=True)
    assert "staat in de wachtrij" in antwoord.data.decode()
    assert SyncTaak.query.filter_by(medewerker_id=gekoppeld.id, soort="volledig").count() == 1
    SyncTaak.query.update({"status": "fout"})
    db.session.commit()
    antwoord = als_beheerder.post("/beheer/agenda/opnieuw", follow_redirects=True)
    assert "1 mislukte taken worden opnieuw geprobeerd" in antwoord.data.decode()


def test_ics_link_maken_en_intrekken(app, gekoppeld, als_beheerder):
    url = f"/beheer/agenda/{gekoppeld.id}/ics"
    assert "Nieuwe ICS-link gemaakt" in als_beheerder.post(url, follow_redirects=True).data.decode()
    assert db.session.get(Medewerker, gekoppeld.id).ics_token
    antwoord = als_beheerder.post(url, data={"intrekken": "1"}, follow_redirects=True)
    assert "werkt niet meer" in antwoord.data.decode()
    assert db.session.get(Medewerker, gekoppeld.id).ics_token == ""
