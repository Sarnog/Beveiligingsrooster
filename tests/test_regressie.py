"""Regressietests voor de bevindingen uit de audit van versie 1.1.2.

Elke test hoort bij één bevinding (C = critical, H = high, M = medium, L = low,
S = security). De test faalde op de oude code en slaagt na de reparatie.
"""

import os
import sqlite3
from datetime import datetime, timedelta

import pytest

from app import worker
from app.extensions import db
from app.models import Logboek, LoginPoging
from app.services import backup, instellingen, klok

# ---------------------------------------------------------------------------
# Hulpjes
# ---------------------------------------------------------------------------


class Klok:
    """Een klok die bij elke aanroep één seconde verder loopt (unieke back-upnamen)."""

    def __init__(self, start: datetime) -> None:
        self.tijd = start

    def __call__(self) -> datetime:
        self.tijd += timedelta(seconds=1)
        return self.tijd


class KapotteVerbinding:
    """Een echte SQLite-verbinding, behalve dat backup() faalt (schijf vol)."""

    def __init__(self, echt):
        self._echt = echt

    def backup(self, *args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    def __getattr__(self, naam):
        return getattr(self._echt, naam)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class KapotSqlite:
    """Nep-module voor backup.sqlite3: connect() werkt, backup() mislukt."""

    OperationalError = sqlite3.OperationalError
    DatabaseError = sqlite3.DatabaseError

    def connect(self, *args, **kwargs):
        return KapotteVerbinding(sqlite3.connect(*args, **kwargs))


def _is_geldige_db(pad: str) -> bool:
    if os.path.getsize(pad) == 0:
        return False
    verbinding = sqlite3.connect(pad)
    try:
        return verbinding.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and bool(
            verbinding.execute("SELECT count(*) FROM sqlite_master").fetchone()[0])
    finally:
        verbinding.close()


# ---------------------------------------------------------------------------
# C1 · Back-uprotatie gooit alle goede back-ups weg na een tijdelijke fout
# ---------------------------------------------------------------------------

def test_c1_mislukte_backups_verdringen_goede_niet(app, klaar, monkeypatch):
    instellingen.schrijf("backup_bewaren", "6")
    db.session.commit()
    monkeypatch.setattr(klok, "nu", Klok(datetime(2026, 3, 1, 1, 0)))
    goed = [backup.maak_backup() for _ in range(5)]

    planning = worker.Planning()
    moment = datetime(2026, 3, 2, 2, 0)
    monkeypatch.setattr(backup, "sqlite3", KapotSqlite())
    for _ in range(10):
        try:
            worker.een_ronde(planning, moment)
        except Exception:  # noqa: BLE001 - oude code liet de fout door
            pass
        moment += timedelta(minutes=31)  # na de backoff mag het opnieuw
    monkeypatch.setattr(backup, "sqlite3", sqlite3)
    worker.een_ronde(planning, moment)

    bestanden = os.listdir(backup.backup_map())
    assert not [n for n in bestanden if not n.endswith(".db")]  # geen .tmp-resten
    paden = [os.path.join(backup.backup_map(), n) for n in bestanden]
    assert all(_is_geldige_db(p) for p in paden), "lege of halve back-up gevonden"
    assert all(os.path.exists(p) for p in goed)  # de oude goede back-ups staan er nog
    assert len(paden) == 6
    assert Logboek.query.filter_by(actie="Back-up mislukt").count() >= 1


def test_c1_backoff_na_mislukte_backup(app, klaar, monkeypatch):
    """Na een mislukte back-up niet elke ronde (5 s) opnieuw proberen."""
    pogingen = []

    def mislukt(label=""):
        pogingen.append(label)
        raise OSError("schijf vol")

    monkeypatch.setattr(backup, "maak_backup", mislukt)
    planning = worker.Planning()
    moment = datetime(2026, 3, 2, 3, 0)
    for _ in range(20):
        worker.een_ronde(planning, moment)
        moment += timedelta(seconds=5)
    assert len(pogingen) == 1
    worker.een_ronde(planning, moment + timedelta(minutes=31))
    assert len(pogingen) == 2


def test_c1_ruim_oude_op_telt_alleen_geldige_automatische(app, klaar):
    instellingen.schrijf("backup_bewaren", "2")
    db.session.commit()
    map_ = backup.backup_map()
    for naam in ("rooster-20260101-010000.db", "rooster-20260102-010000.db",
                 "rooster-20260103-010000.db"):
        with open(os.path.join(map_, naam), "wb") as f:
            f.write(b"x")
    open(os.path.join(map_, "rooster-20260104-010000.db"), "wb").close()  # leeg
    with open(os.path.join(map_, "rooster-20260105-010000-handmatig.db"), "wb") as f:
        f.write(b"x")
    backup.ruim_oude_op()
    over = sorted(os.listdir(map_))
    assert "rooster-20260102-010000.db" in over and "rooster-20260103-010000.db" in over
    assert "rooster-20260101-010000.db" not in over
    assert "rooster-20260105-010000-handmatig.db" in over


# ---------------------------------------------------------------------------
# C2 · Anonieme bezoeker kan de database onbeperkt vullen via /login
# ---------------------------------------------------------------------------

def _db_grootte(app) -> int:
    with db.engine.connect() as verbinding:
        verbinding.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    pad = app.config["SQLALCHEMY_DATABASE_URI"].removeprefix("sqlite:///")
    return os.path.getsize(pad)


def test_c2_lange_gebruikersnaam_vult_database_niet(app, client, klaar):
    voor = _db_grootte(app)
    naam = "a" * 400_000
    for _ in range(40):
        antwoord = client.post("/login", data={"gebruikersnaam": naam, "wachtwoord": "x"})
        assert antwoord.status_code in (401, 429)
    db.session.remove()
    groei = _db_grootte(app) - voor
    assert groei < 32 * 1024, f"database groeide {groei} bytes"
    assert max(len(p.gebruikersnaam) for p in LoginPoging.query.all()) <= 64
    assert Logboek.query.filter_by(actie="Login geblokkeerd").count() <= 1


def test_c2_logboekvelden_centraal_begrensd(app, klaar):
    from app.services import logboek

    logboek.log("Test", "d" * 5000, oud="o" * 5000, nieuw="n" * 5000, gebruiker="g" * 500,
                medewerker="m" * 500, veld="v" * 500)
    db.session.commit()
    regel = Logboek.query.filter_by(actie="Test").one()
    assert len(regel.details) <= 1000 and len(regel.oude_waarde) <= 1000
    assert len(regel.nieuwe_waarde) <= 1000 and len(regel.gebruiker) <= 64
    assert len(regel.medewerker) <= 120 and len(regel.veld) <= 40


def test_c2_oude_loginpogingen_worden_opgeruimd(app, klaar):
    nu = klok.utc_nu()
    db.session.add(LoginPoging(gebruikersnaam="x", ip="1.2.3.4", tijdstip=nu - timedelta(days=2)))
    db.session.add(LoginPoging(gebruikersnaam="y", ip="1.2.3.4", tijdstip=nu))
    db.session.commit()
    worker.een_ronde(worker.Planning(), datetime(2026, 3, 2, 1, 0))
    assert [p.gebruikersnaam for p in LoginPoging.query.all()] == ["y"]


def test_c2_geblokkeerd_maar_een_keer_gelogd(app, client, klaar):
    for _ in range(12):
        client.post("/login", data={"gebruikersnaam": "beheerder", "wachtwoord": "fout"})
    assert Logboek.query.filter_by(actie="Login geblokkeerd").count() == 1
    assert LoginPoging.query.count() == 5  # geblokkeerde pogingen schrijven niets meer


@pytest.fixture(autouse=True)
def _geen_echte_google(monkeypatch):
    """De worker mag in deze tests nooit echt met Google praten."""
    from app.services import google_agenda
    from app.services.google_agenda import AgendaFout

    def geen():
        raise AgendaFout("geen Google in tests")

    monkeypatch.setattr(google_agenda, "klant", geen)
