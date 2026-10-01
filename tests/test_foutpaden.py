"""Foutpaden en randgevallen die eerder ongetest waren (o.a. uit mutatietesten)."""

from datetime import date, datetime, timedelta

import pytest

from app import worker
from app.extensions import db
from app.models import Dienst, Dienstcode, Gebruiker, Logboek, Medewerker, SyncTaak
from app.services import backup, klok, logboek, sync, sync_planning
from app.services.google_agenda import AgendaFout
from app.services.tijden import OngeldigeTijd, normaliseer_tijd
from app.services.urenberekening import bereken_uren
from app.services.voorbeeldpakket import laad_voorbeeldpakket
from app.services.weekrooster import Wijziging, wijzig_cellen

from .conftest import WACHTWOORD, login, maak_gebruiker

MAANDAG = date(2026, 3, 2)


@pytest.fixture
def mw(klaar):
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1)
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


# ---------- Tijden en uren ----------

@pytest.mark.parametrize("invoer, verwacht", [
    ("7:3", "07:30"), ("07", "07:00"), ("7", "07:00"), ("715", "07:15"), ("0715", "07:15"),
    ("7.15", "07:15"), ("7,15", "07:15"), ("24:00", "00:00"), ("2400", "00:00"), ("", None),
    (None, None), (" 23:59 ", "23:59"),
])
def test_normaliseer_tijd(invoer, verwacht):
    assert normaliseer_tijd(invoer) == verwacht


@pytest.mark.parametrize("invoer", ["7:", ":30", "24:01", "25", "7:60", "12345", "1:2:3", "abc", "7u"])
def test_normaliseer_tijd_fout(invoer):
    with pytest.raises(OngeldigeTijd):
        normaliseer_tijd(invoer)


def test_begin_gelijk_aan_eind_is_nul_uur():
    """Vastgelegd gedrag: begin == eind telt 0 uur, precies zoals de oude Excel-VBA
    (alleen eind < begin telt als 'over middernacht'). Een 24-uursdienst voer je in
    met zelf ingevulde uren."""
    assert bereken_uren("08:00", "08:00") == 0.0
    assert bereken_uren("00:00", "00:00", 2.0) == 0.0


# ---------- Backoff en maximum aantal pogingen ----------

def test_wachttijd():
    assert sync.wachttijd(0) == timedelta(seconds=30)
    assert [sync.wachttijd(p).total_seconds() for p in (1, 2, 3, 7, 8)] == [30, 60, 120, 1920, 3600]


def test_verwerk_fout_grenzen(app, mw):
    taak = SyncTaak(medewerker_id=mw.id, datum=MAANDAG, soort="dag", status="bezig")
    db.session.add(taak)
    db.session.commit()
    tijdelijk = AgendaFout("503", tijdelijk=True, status=503)
    for poging in range(1, sync.MAX_POGINGEN):
        sync._verwerk_fout(taak, tijdelijk)
        assert (taak.pogingen, taak.status) == (poging, "wacht")
        assert taak.niet_voor > klok.utc_nu()
    sync._verwerk_fout(taak, tijdelijk)  # de zesde keer: definitief
    assert (taak.pogingen, taak.status) == (sync.MAX_POGINGEN, "fout")
    assert "503" in mw.agenda_laatste_fout


def test_blijvende_fout_meteen_definitief(app, mw):
    taak = SyncTaak(medewerker_id=None, datum=None, soort="ontkoppel", status="bezig")
    db.session.add(taak)
    db.session.commit()
    sync._verwerk_fout(taak, AgendaFout("403", tijdelijk=False, status=403))
    assert (taak.pogingen, taak.status) == (1, "fout")
    assert Logboek.query.filter_by(actie="Agenda-sync fout").count() == 1


def test_geen_sleutel_zet_alle_taken_in_backoff(app, mw):
    mw.agenda_modus, mw.agenda_id = "B", "x"
    db.session.commit()
    sync_planning.plan_volledig(mw)
    SyncTaak.query.update({"niet_voor": datetime(2000, 1, 1)})
    db.session.commit()
    assert sync.verwerk_wachtrij(lambda: (_ for _ in ()).throw(AgendaFout("geen sleutel"))) == 0
    assert SyncTaak.query.one().status == "fout"


# ---------- Worker ----------

def test_worker_opschonen_mislukt_backup_gaat_door(app, klaar, monkeypatch, caplog):
    def kapot(nu=None):
        raise RuntimeError("logboek stuk")

    monkeypatch.setattr(logboek, "opschonen", kapot)
    planning = worker.Planning()
    with caplog.at_level("ERROR"):
        worker.een_ronde(planning, datetime(2026, 3, 2, 3, 0))
    assert "opschonen" in caplog.text
    assert len(backup.lijst_backups()) == 1
    assert planning.opschonen_gedaan == date(2026, 3, 2)  # morgen opnieuw, niet elke ronde


def test_worker_zonder_setup_doet_alleen_sync(app):
    worker.een_ronde(worker.Planning(), datetime(2026, 3, 2, 3, 0))
    assert backup.lijst_backups() == []


def test_worker_backup_een_keer_per_nacht(app, klaar):
    planning = worker.Planning()
    worker.een_ronde(planning, datetime(2026, 3, 2, 1, 59))
    assert backup.lijst_backups() == []  # nog niet na 02:00
    worker.een_ronde(planning, datetime(2026, 3, 2, 2, 0))
    worker.een_ronde(planning, datetime(2026, 3, 2, 2, 0, 5))
    assert len(backup.lijst_backups()) == 1


# ---------- Gebruikersbeheer ----------

def test_laatste_beheerder_niet_deactiveren(als_beheerder, klaar):
    beheerder = klaar["beheerder"]
    antwoord = als_beheerder.post(f"/beheer/gebruikers/{beheerder.id}", data={
        "gebruikersnaam": "beheerder", "weergavenaam": "B", "rol": "beheerder"})  # actief uit
    assert antwoord.status_code == 400 and "laatste beheerder" in antwoord.data.decode()
    assert db.session.get(Gebruiker, beheerder.id).actief


def test_beheerder_degraderen_als_er_een_ander_is(app, als_beheerder, klaar):
    tweede = maak_gebruiker("tweede", "beheerder")
    antwoord = als_beheerder.post(f"/beheer/gebruikers/{tweede.id}", data={
        "gebruikersnaam": "tweede", "weergavenaam": "T", "rol": "gebruiker", "actief": "1"})
    assert antwoord.status_code == 302
    assert not db.session.get(Gebruiker, tweede.id).is_beheerder


def test_gebruiker_verwijderen(app, als_beheerder, klaar):
    tweede = maak_gebruiker("tweede", "beheerder")
    als_beheerder.post(f"/beheer/gebruikers/{tweede.id}/verwijder")
    als_beheerder.post(f"/beheer/gebruikers/{klaar['gebruiker'].id}/verwijder")
    assert {g.gebruikersnaam for g in Gebruiker.query.all()} == {"beheerder"}
    assert Logboek.query.filter_by(actie="Account verwijderd").count() == 2


def test_wachtwoord_reset_door_beheerder(app, als_beheerder, klaar):
    antwoord = als_beheerder.post(f"/beheer/gebruikers/{klaar['gebruiker'].id}/reset")
    pagina = antwoord.data.decode()
    import html

    pagina = html.unescape(pagina)
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    assert gebruiker.moet_wachtwoord_wijzigen
    tijdelijk = pagina.split('<p class="groot-code" data-kopieer>')[1].split("</p>")[0]
    collega = app.test_client()
    assert login(collega, "collega", tijdelijk).status_code == 302
    assert login(app.test_client(), "collega", WACHTWOORD).status_code == 401


@pytest.mark.parametrize("gegevens, melding", [
    ({"gebruikersnaam": "x"}, "2-64 tekens"),
    ({"gebruikersnaam": "collega"}, "bestaat al"),
    ({"weergavenaam": ""}, "weergavenaam"),
    ({"rol": "baas"}, "Ongeldige rol"),
    ({"medewerker_id": "999"}, "Onbekende medewerker"),
    ({"wachtwoord": "kort"}, "minimaal"),
])
def test_nieuwe_gebruiker_controles(als_beheerder, klaar, gegevens, melding):
    formulier = {"gebruikersnaam": "nieuw", "weergavenaam": "Nieuw", "rol": "gebruiker",
                 "wachtwoord": "lang-genoeg-123", "actief": "1"}
    formulier.update(gegevens)
    antwoord = als_beheerder.post("/beheer/gebruikers/nieuw", data=formulier)
    assert antwoord.status_code == 400 and melding in antwoord.data.decode()


def test_gebruikersschermen(als_beheerder, klaar):
    assert als_beheerder.get("/beheer/gebruikers").status_code == 200
    assert als_beheerder.get("/beheer/gebruikers/nieuw").status_code == 200
    assert als_beheerder.get(f"/beheer/gebruikers/{klaar['gebruiker'].id}").status_code == 200


# ---------- Dienstcodes: standaardtijden toepassen ----------

def test_standaardtijden_toepassen(app, als_beheerder, mw):
    morgen = klok.vandaag() + timedelta(days=1)
    gisteren = klok.vandaag() - timedelta(days=1)
    wijzig_cellen([Wijziging(mw.id, morgen, "code", "4"), Wijziging(mw.id, morgen, "eind", "18:00"),
                   Wijziging(mw.id, gisteren, "code", "4"), Wijziging(mw.id, gisteren, "eind", "18:00")])
    code = Dienstcode.query.filter_by(nummer=4).one()
    pagina = als_beheerder.get(f"/beheer/dienstcodes/{code.id}/standaardtijden").data.decode()
    assert morgen.strftime("%d-%m-%Y") in pagina
    mw.agenda_modus, mw.agenda_id = "B", "agenda-a"
    db.session.commit()
    als_beheerder.post(f"/beheer/dienstcodes/{code.id}/standaardtijden")
    db.session.expire_all()
    toekomst = Dienst.query.filter_by(datum=morgen).one()
    verleden = Dienst.query.filter_by(datum=gisteren).one()
    assert (toekomst.eind, toekomst.tijden_handmatig, toekomst.uren_berekend) == ("15:45", False, 8.0)
    assert verleden.eind == "18:00"  # het verleden blijft zoals het was
    assert SyncTaak.query.filter_by(datum=morgen).count() == 1


# ---------- Week kopiëren ----------

def test_week_kopieren_een_medewerker(app, als_beheerder, mw):
    andere = Medewerker(naam="Medewerker B", initialen="MB", volgorde=2)
    db.session.add(andere)
    db.session.commit()
    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4"), Wijziging(andere.id, MAANDAG, "code", "5")])
    antwoord = als_beheerder.post("/week/2026/10/kopieer", data={"naar": "2026-W12",
                                                                "medewerker_id": str(mw.id)})
    assert antwoord.headers["Location"].endswith("/week/2026/12")
    doel = MAANDAG + timedelta(weeks=2)
    assert [d.medewerker_id for d in Dienst.query.filter_by(datum=doel).all()] == [mw.id]


@pytest.mark.parametrize("naar", ["", "abc", "2026-W10", "2026-W54", "1800-W01"])
def test_week_kopieren_ongeldige_doelweek(app, als_beheerder, mw, naar):
    antwoord = als_beheerder.post("/week/2026/10/kopieer", data={"naar": naar}, follow_redirects=True)
    assert "doelweek" in antwoord.data.decode()


def test_week_kopieren_onbekende_medewerker(als_beheerder, mw):
    assert als_beheerder.post("/week/2026/10/kopieer", data={"naar": "2026-W11",
                                                             "medewerker_id": "999"}).status_code == 404
