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


# ---------------------------------------------------------------------------
# H1 · Zelfde dienstcode opnieuw invoeren reset handmatige tijden stil
# ---------------------------------------------------------------------------

MAANDAG = datetime(2026, 3, 2).date()  # week 10 van 2026


@pytest.fixture
def mw(klaar):
    from app.models import Medewerker
    from app.services.voorbeeldpakket import laad_voorbeeldpakket

    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1)
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def test_h1_zelfde_code_opnieuw_laat_handmatige_tijden_staan(app, mw):
    from app.models import Dienst
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4"), Wijziging(mw.id, MAANDAG, "eind", "18:00")])
    dienst = Dienst.query.one()
    voor = (dienst.eind, dienst.tijden_handmatig, dienst.uren_berekend, dienst.versie)
    regels = Logboek.query.count()
    assert voor[0] == "18:00" and voor[1] is True

    _, fouten = wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4", versie=dienst.versie)])
    assert fouten == []
    db.session.expire_all()
    dienst = Dienst.query.one()
    assert (dienst.eind, dienst.tijden_handmatig, dienst.uren_berekend, dienst.versie) == voor
    assert Logboek.query.count() == regels


# ---------------------------------------------------------------------------
# H2 · Excel-import is niet atomair
# ---------------------------------------------------------------------------

def _import_dienst(naam, dag, **extra):
    from app.services.excel_import import ImportDienst

    waarden = dict(naam=naam, datum=dag, code=None, dienstnaam="Cursus", begin="08:00",
                   eind="16:00", opmerking="", opm_begin=None, opm_eind=None, excel_uren=None)
    waarden.update(extra)
    return ImportDienst(**waarden)


def _bestaande_dienst(mw):
    from app.models import Dienst

    db.session.add(Dienst(medewerker_id=mw.id, datum=MAANDAG, dienstnaam_override="Oud",
                          begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()


def test_h2_dubbele_dienst_laat_oud_rooster_heel(app, mw):
    from app.models import Dienst, Feestdag
    from app.services.excel_import import ImportMedewerker, ImportPlan, importeer

    _bestaande_dienst(mw)
    Feestdag.query.delete()  # verse installatie: feestdagen bestaan nog niet
    db.session.commit()
    dinsdag = MAANDAG + timedelta(days=1)
    plan = ImportPlan(jaar=2026, weken=[10],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", dinsdag),
                                _import_dienst("Medewerker A", dinsdag)])
    with pytest.raises(Exception):  # noqa: B017 - oude code: IntegrityError, nieuw: ImportFout
        importeer(plan)
    db.session.rollback()
    assert Dienst.query.filter_by(datum=MAANDAG).one().dienstnaam_override == "Oud"


def test_h2_fout_halverwege_draait_alles_terug(app, mw, monkeypatch):
    from app.models import Dienst, Feestdag
    from app.services import excel_import
    from app.services.excel_import import ImportMedewerker, ImportPlan

    _bestaande_dienst(mw)
    Feestdag.query.delete()
    db.session.commit()

    def kapot():
        raise RuntimeError("onverwacht")

    monkeypatch.setattr(excel_import, "markeer_bijgewerkt", kapot)
    plan = ImportPlan(jaar=2026, weken=[10],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", MAANDAG + timedelta(days=2))])
    with pytest.raises(Exception):  # noqa: B017
        excel_import.importeer(plan)
    db.session.rollback()
    assert Dienst.query.filter_by(datum=MAANDAG).one().dienstnaam_override == "Oud"
    assert Dienst.query.count() == 1


def test_h2_droogloop_meldt_dubbele_diensten_en_scherm_geeft_nette_fout(app, als_beheerder, tmp_path):
    import io

    import openpyxl

    boek = openpyxl.Workbook()
    lijsten = boek.active
    lijsten.title = "Lijsten"
    lijsten.cell(2, 2, "MD")
    lijsten.cell(2, 3, "Medewerker Dubbel")
    boek.create_sheet("Kalender")["E2"] = 2026
    week = boek.create_sheet("W10")
    for blok in (0, 1):  # dezelfde naam twee keer in één week
        week.cell(4 + 4 * blok, 2, "Medewerker Dubbel")
        week.cell(6 + 4 * blok, 4, "Cursus")
        week.cell(7 + 4 * blok, 4, datetime(1900, 1, 1, 8, 0).time())
        week.cell(7 + 4 * blok, 5, datetime(1900, 1, 1, 16, 0).time())
    pad = str(tmp_path / "dubbel.xlsx")
    boek.save(pad)

    from app.services.excel_import import lees_bestand

    plan = lees_bestand(pad)
    assert any("dubbel" in w.lower() for w in plan.waarschuwingen)

    with open(pad, "rb") as f:
        als_beheerder.post("/beheer/importeren", data={"bestand": (io.BytesIO(f.read()), "x.xlsx")},
                           content_type="multipart/form-data")
    antwoord = als_beheerder.post("/beheer/importeren/voorbeeld", data={"bevestig": "1"},
                                  follow_redirects=True)
    assert antwoord.status_code == 200
    assert "niet geïmporteerd" in antwoord.data.decode()


# ---------------------------------------------------------------------------
# H3 · Wijziging tijdens een lopende agenda-sync gaat verloren
# ---------------------------------------------------------------------------

def _plan_dag_in_ander_proces(medewerker_id, datum, wijzig_dienst):
    """Doet wat een webverzoek doet (dienst wijzigen + plan_dag), in een eigen sessie."""
    from sqlalchemy.orm import Session

    from app.models import Dienst, SyncTaak

    with Session(db.engine) as sessie:
        dienst = sessie.query(Dienst).filter_by(medewerker_id=medewerker_id, datum=datum).one()
        wijzig_dienst(dienst)
        dienst.versie += 1
        straks = klok.utc_nu() + timedelta(seconds=10)
        bestaand = sessie.query(SyncTaak).filter_by(
            medewerker_id=medewerker_id, datum=datum, soort="dag", status="wacht").first()
        if bestaand:
            bestaand.niet_voor = straks
        else:
            sessie.add(SyncTaak(medewerker_id=medewerker_id, datum=datum, soort="dag",
                                niet_voor=straks))
        sessie.commit()


@pytest.fixture
def gekoppeld(mw, monkeypatch):
    mw.agenda_modus, mw.agenda_id = "B", "agenda-a"
    db.session.commit()
    return mw


def _wachtrij_nu():
    from app.models import SyncTaak
    from app.services import sync

    SyncTaak.query.update({"niet_voor": datetime(2000, 1, 1)})
    db.session.commit()
    return sync.verwerk_wachtrij()


def test_h3_wijziging_tijdens_sync_blijft_in_wachtrij(app, gekoppeld, monkeypatch):
    from app.models import SyncTaak
    from app.services import google_agenda
    from app.services.weekrooster import Wijziging, wijzig_cellen

    from .test_agenda import NepKlant

    class GelijktijdigeKlant(NepKlant):
        def maak_afspraak(self, agenda_id, body):
            def later(dienst):
                dienst.eind = "18:00"

            _plan_dag_in_ander_proces(gekoppeld.id, MAANDAG, later)
            return super().maak_afspraak(agenda_id, body)

    klant = GelijktijdigeKlant()
    monkeypatch.setattr(google_agenda, "klant", lambda: klant)
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    _wachtrij_nu()
    db.session.expire_all()
    wachtend = SyncTaak.query.filter_by(status="wacht").count()
    afspraak = next(iter(klant.agendas["agenda-a"].values()))
    assert wachtend == 1 or afspraak["end"]["dateTime"].endswith("18:00:00")

    # En de volgende ronde zet de nieuwe tijd in Google
    monkeypatch.setattr(google_agenda, "klant", lambda: NepKlant.__new__(NepKlant))
    klant2 = NepKlant()
    klant2.agendas = klant.agendas
    monkeypatch.setattr(google_agenda, "klant", lambda: klant2)
    _wachtrij_nu()
    afspraak = next(iter(klant.agendas["agenda-a"].values()))
    assert afspraak["end"]["dateTime"].endswith("18:00:00")
    assert len(klant.agendas["agenda-a"]) == 1


def test_h3_blijven_hangen_op_bezig_wordt_hersteld(app, gekoppeld, monkeypatch):
    from app.models import SyncTaak
    from app.services import google_agenda, sync

    from .test_agenda import NepKlant

    monkeypatch.setattr(google_agenda, "klant", NepKlant)
    db.session.add(SyncTaak(medewerker_id=gekoppeld.id, datum=MAANDAG, soort="dag",
                            status="bezig", niet_voor=klok.utc_nu() - timedelta(minutes=11)))
    db.session.add(SyncTaak(medewerker_id=gekoppeld.id, datum=MAANDAG + timedelta(days=1),
                            soort="dag", status="bezig", niet_voor=klok.utc_nu()))
    db.session.commit()
    sync.verwerk_wachtrij()
    db.session.expire_all()
    # De oude 'bezig'-taak is opnieuw opgepakt en klaar; de verse loopt nog (ander proces)
    assert [t.status for t in SyncTaak.query.all()] == ["bezig"]


# ---------------------------------------------------------------------------
# H4 · Gedeelde agenda (modus B): sync verwijdert afspraken van collega's
# ---------------------------------------------------------------------------

def _team(monkeypatch):
    from app.models import Medewerker
    from app.services import google_agenda, sync
    from app.services.weekrooster import Wijziging, wijzig_cellen

    from .test_agenda import NepKlant

    klant = NepKlant()
    monkeypatch.setattr(google_agenda, "klant", lambda: klant)
    a = Medewerker(naam="Collega A", initialen="CA", agenda_modus="B", agenda_id="team")
    b = Medewerker(naam="Collega B", initialen="CB", agenda_modus="B", agenda_id="team")
    db.session.add_all([a, b])
    db.session.commit()
    dag = sync.sync_periode()[0] + timedelta(days=14)  # binnen de sync-periode
    wijzig_cellen([Wijziging(a.id, dag, "code", "4"), Wijziging(b.id, dag, "code", "5")])
    _wachtrij_nu()
    assert len(klant.agendas["team"]) == 2
    return klant, a, b


def _van(klant, medewerker):
    return [e for e in klant.agendas["team"].values()
            if e["extendedProperties"]["private"]["medewerker_id"] == str(medewerker.id)]


def test_h4_volledige_sync_laat_collega_met_rust(app, mw, monkeypatch):
    from app.services import sync_planning

    klant, a, b = _team(monkeypatch)
    sync_planning.plan_volledig(a)
    _wachtrij_nu()
    assert len(_van(klant, b)) == 1 and len(_van(klant, a)) == 1


def test_h4_ontkoppelen_modus_b_wist_alleen_eigen_afspraken(app, mw, monkeypatch):
    from app.services import sync_planning

    klant, a, b = _team(monkeypatch)
    sync_planning.plan_ontkoppel(a, verwijder=True)
    db.session.commit()
    _wachtrij_nu()
    assert _van(klant, a) == [] and len(_van(klant, b)) == 1


def test_h4_oude_afspraak_zonder_medewerker_id(app, mw, monkeypatch):
    """Afspraken van vóór de medewerker-markering: alleen weg als de dienst van A is."""
    from app.models import Dienst
    from app.services import sync

    klant, a, b = _team(monkeypatch)
    dienst_b = Dienst.query.filter_by(medewerker_id=b.id).one()
    klant.agendas["team"]["oud-b"] = {"id": "oud-b", "extendedProperties": {"private": {
        "bron": "beveiligingsrooster", "dienst_id": str(dienst_b.id)}}}
    klant.agendas["team"]["oud-a"] = {"id": "oud-a", "extendedProperties": {"private": {
        "bron": "beveiligingsrooster", "dienst_id": "999999"}}}
    dienst_a = Dienst.query.filter_by(medewerker_id=a.id).one()
    klant.agendas["team"]["oud-a2"] = {"id": "oud-a2", "extendedProperties": {"private": {
        "bron": "beveiligingsrooster", "dienst_id": str(dienst_a.id)}}}
    sync.sync_volledig(klant, a)
    assert "oud-b" in klant.agendas["team"] and "oud-a" in klant.agendas["team"]
    assert "oud-a2" not in klant.agendas["team"]


# ---------------------------------------------------------------------------
# H5 · Excel-import koppelt op initialen aan de verkeerde medewerker
# ---------------------------------------------------------------------------

def test_h5_alleen_initialen_gelijk_geeft_nieuwe_medewerker(app, klaar, tmp_path):
    from app.models import Dienst, Medewerker
    from app.services.excel_import import importeer, lees_bestand

    from .test_import_backup import maak_testbestand

    bestaand = Medewerker(naam="Iemand Anders", initialen="MVA")  # zelfde initialen
    zelfde_naam = Medewerker(naam="Medewerker Vijf B", initialen="XYZ")
    db.session.add_all([bestaand, zelfde_naam])
    db.session.commit()
    pad = str(tmp_path / "oud.xlsx")
    maak_testbestand(pad)

    plan = lees_bestand(pad)
    koppeling = {m.naam: (m.koppeling, m.bestaand_id) for m in plan.medewerkers}
    assert koppeling["Medewerker Vijf A"] == ("initialen", None)
    assert koppeling["Medewerker Vijf B"] == ("naam", zelfde_naam.id)
    assert any("MVA" in w and "Iemand Anders" in w for w in plan.waarschuwingen)

    importeer(plan)
    nieuw = Medewerker.query.filter_by(naam="Medewerker Vijf A").one()
    assert nieuw.id != bestaand.id and nieuw.initialen not in ("MVA", "")
    assert Dienst.query.filter_by(medewerker_id=bestaand.id).count() == 0
    assert Dienst.query.filter_by(medewerker_id=zelfde_naam.id).count() == 1


# ---------------------------------------------------------------------------
# H6 · Back-up van een nieuwere versie terugzetten legt de app plat
# M6 · Uitkomst van integrity_check werd genegeerd
# ---------------------------------------------------------------------------

@pytest.fixture
def gemigreerd(app):
    from flask_migrate import upgrade

    db.drop_all()
    upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    return app


def _revisie() -> str:
    with db.engine.connect() as verbinding:
        return verbinding.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()


def test_h6_backup_van_nieuwere_versie_wordt_geweigerd(gemigreerd):
    from app.models import Medewerker

    pad = backup.maak_backup("test")
    verbinding = sqlite3.connect(pad)
    verbinding.execute("UPDATE alembic_version SET version_num = '0009_toekomst'")
    verbinding.commit()
    verbinding.close()
    db.session.add(Medewerker(naam="Na de back-up", initialen="NB"))
    db.session.commit()
    revisie = _revisie()

    with pytest.raises(ValueError, match="nieuwere versie"):
        backup.zet_terug(pad)
    db.session.remove()
    assert Medewerker.query.filter_by(initialen="NB").count() == 1
    assert _revisie() == revisie


def test_h6_mislukte_upgrade_zet_veiligheidsbackup_terug(gemigreerd, monkeypatch):
    import flask_migrate

    from app.models import Medewerker

    pad = backup.maak_backup("test")
    db.session.add(Medewerker(naam="Na de back-up", initialen="NB"))
    db.session.commit()

    def kapotte_upgrade(*args, **kwargs):
        raise SystemExit(1)  # zo stopt Flask-Migrate bij een fout

    monkeypatch.setattr(flask_migrate, "upgrade", kapotte_upgrade)
    with pytest.raises(ValueError, match="teruggezet"):
        backup.zet_terug(pad)
    db.session.remove()
    assert Medewerker.query.filter_by(initialen="NB").count() == 1


def test_m6_beschadigde_backup_wordt_geweigerd(gemigreerd):
    from app.models import Medewerker

    db.session.add_all([Medewerker(naam=f"Medewerker {i}", initialen=f"M{i}", ics_token=f"t{i}")
                        for i in range(20)])
    db.session.commit()
    pad = backup.maak_backup("test")
    verbinding = sqlite3.connect(pad)
    verbinding.execute("PRAGMA writable_schema = ON")
    verbinding.execute("UPDATE sqlite_master SET sql = 'CREATE INDEX ix_medewerker_ics_token "
                       "ON medewerker (naam)' WHERE name = 'ix_medewerker_ics_token'")
    verbinding.commit()
    verbinding.close()
    with pytest.raises(ValueError, match="beschadigd"):
        backup.controleer_backupbestand(pad)


def test_h6_scherm_ruimt_upload_op_bij_elke_fout(gemigreerd, client, monkeypatch):
    import io

    from .conftest import login, maak_gebruiker

    maak_gebruiker("beheerder", "beheerder")
    login(client, "beheerder")

    def kapot(pad):
        raise RuntimeError("onverwacht")

    monkeypatch.setattr(backup, "zet_terug", kapot)
    antwoord = client.post("/beheer/backups/terugzetten", data={
        "bevestig": "1", "bestand": (io.BytesIO(b"x"), "x.db")},
        content_type="multipart/form-data", follow_redirects=True)
    assert antwoord.status_code == 200 and "Terugzetten mislukt" in antwoord.data.decode()
    assert not [b for b in backup.lijst_backups() if b["naam"].endswith("-upload.db")]


# ---------------------------------------------------------------------------
# M1 · inf/nan als toeslagfactor
# M2 · tijdzone als vrije tekst, drie tijdzonebronnen
# M3 · blanco-code gelijk aan een bestaande dienstcode
# ---------------------------------------------------------------------------

def _instellingen_formulier(**anders) -> dict:
    formulier = {s: instellingen.lees(s) for s in instellingen.STANDAARD}
    formulier.update({"eerste_jaar": "2026", "tijdzone": "Europe/Amsterdam"})
    formulier.pop("deellink_actief")
    formulier.pop("opmerkingtijden_meetellen")
    formulier.update(anders)
    return formulier


@pytest.mark.parametrize("waarde", ["inf", "nan", "-inf", "1e400", "11", "0"])
def test_m1_toeslagfactor_moet_eindig_en_redelijk_zijn(app, als_beheerder, waarde):
    antwoord = als_beheerder.post("/beheer/instellingen",
                                  data=_instellingen_formulier(toeslag_zaterdag=waarde))
    assert antwoord.status_code == 400
    assert instellingen.lees("toeslag_zaterdag") == "1.5"


def test_m1_feestdagfactor_inf_geweigerd(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/instellingen", data=_instellingen_formulier(
        feestdagtoeslag_aan="1", toeslag_feestdag="inf"))
    assert antwoord.status_code == 400


def test_m1_getal_en_lees_float_weigeren_inf_nan(app, klaar):
    from app.blueprints.hulp import getal

    assert getal("inf") is None and getal("nan") is None and getal("1,5") == 1.5
    instellingen.schrijf("toeslag_zaterdag", "inf")
    assert instellingen.lees_float("toeslag_zaterdag") is None
    assert instellingen.toeslagen()["factor_zaterdag"] == 1.5


def test_m1_setup_weigert_inf(app, client):
    from app.services import setup_code

    from .conftest import WACHTWOORD

    client.get("/setup/")
    client.post("/setup/", data={"code": setup_code.lees_code()})
    client.post("/setup/stap/1", data={"gebruikersnaam": "planner", "weergavenaam": "P",
                                       "wachtwoord": WACHTWOORD, "herhaling": WACHTWOORD})
    formulier = {"teamnaam": "T", "tijdzone": "Europe/Amsterdam", "eerste_jaar": "2026",
                 "toeslag_zaterdag": "nan", "toeslag_zondag": "2", "logboek_dagen": "31",
                 "logboek_uren": "0"}
    assert client.post("/setup/stap/2", data=formulier).status_code == 400
    formulier.update(toeslag_zaterdag="1,5", tijdzone="Mars/Olympus")
    assert client.post("/setup/stap/2", data=formulier).status_code == 400
    assert instellingen.lees("tijdzone") != "Mars/Olympus"


def test_m2_ongeldige_tijdzone_geweigerd(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/instellingen",
                                  data=_instellingen_formulier(tijdzone="Mars/Olympus"))
    assert antwoord.status_code == 400 and "tijdzone" in antwoord.data.decode().lower()
    assert instellingen.lees("tijdzone") != "Mars/Olympus"


def test_m2_een_tijdzonebron_voor_klok_ics_en_agenda(app, als_beheerder, mw):
    from app.models import Dienst
    from app.services import ics
    from app.services.google_agenda import afspraak_voor

    antwoord = als_beheerder.post("/beheer/instellingen",
                                  data=_instellingen_formulier(tijdzone="Europe/London"))
    assert antwoord.status_code == 302
    assert klok.tijdzone_naam() == "Europe/London"
    db.session.add(Dienst(medewerker_id=mw.id, datum=klok.vandaag(), dienstnaam_override="X",
                          begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()
    feed = ics.maak_feed(mw)
    assert "X-WR-TIMEZONE:Europe/London" in feed
    assert ics._utc("2026-07-01T07:15:00") == "20260701T061500Z"  # Londen: UTC+1 in de zomer
    assert afspraak_voor(Dienst.query.one()).body["start"]["timeZone"] == "Europe/London"


def test_m3_blanco_code_mag_geen_bestaande_dienstcode_zijn(app, als_beheerder, mw):
    antwoord = als_beheerder.post("/beheer/instellingen", data=_instellingen_formulier(blanco_code="4"))
    assert antwoord.status_code == 400 and "blanco" in antwoord.data.decode().lower()
    assert instellingen.lees("blanco_code") == "15"


# ---------------------------------------------------------------------------
# M4 · ImportError slikte echte fouten; een sync-fout blokkeerde de back-up
# ---------------------------------------------------------------------------

def test_m4_sync_fout_blokkeert_backup_niet(app, klaar, monkeypatch, caplog):
    from app.services import sync

    def kapot(*args, **kwargs):
        raise RuntimeError("sync stuk")

    monkeypatch.setattr(sync, "verwerk_wachtrij", kapot)
    with caplog.at_level("ERROR"):
        worker.een_ronde(worker.Planning(), datetime(2026, 3, 2, 3, 0))
    assert len(backup.lijst_backups()) == 1
    assert "agenda-synchronisatie" in caplog.text


def test_m4_importerror_wordt_niet_ingeslikt(app, klaar, monkeypatch, caplog):
    from app.services import sync

    def kapot(*args, **kwargs):
        raise ImportError("google_auth_httplib2 ontbreekt")

    monkeypatch.setattr(sync, "verwerk_wachtrij", kapot)
    with caplog.at_level("ERROR"):
        worker.een_ronde(worker.Planning(), datetime(2026, 3, 2, 1, 0))
    assert "google_auth_httplib2" in caplog.text


def test_m4_google_afhankelijkheden_in_requirements():
    import pathlib

    tekst = (pathlib.Path(__file__).parent.parent / "requirements.txt").read_text().lower()
    assert "google-auth-httplib2" in tekst and "httplib2" in tekst.replace("google-auth-httplib2", "")


# ---------------------------------------------------------------------------
# M5 · Per-IP-limiet blokkeert iedereen achter een proxy
# ---------------------------------------------------------------------------

def test_m5_juist_wachtwoord_komt_door_een_ip_blokkade(app, client, klaar):
    from .conftest import login

    for i in range(20):  # veel verschillende (fictieve) namen vanaf hetzelfde IP
        client.post("/login", data={"gebruikersnaam": f"onbekend{i}", "wachtwoord": "fout"})
    # Een nieuwe naam met een fout wachtwoord: geblokkeerd
    assert client.post("/login", data={"gebruikersnaam": "nogeen", "wachtwoord": "fout"}).status_code == 429
    # Een collega met het juiste wachtwoord komt er wel in
    assert login(client, "collega").status_code == 302


def test_m5_ip_blokkade_geeft_geen_extra_raadpogingen(app, client, klaar):
    for i in range(20):
        client.post("/login", data={"gebruikersnaam": f"onbekend{i}", "wachtwoord": "fout"})
    client.post("/login", data={"gebruikersnaam": "collega", "wachtwoord": "fout1"})
    # Na één fout tijdens een IP-blokkade helpt zelfs het juiste wachtwoord niet meer
    from .conftest import login

    assert login(client, "collega").status_code == 429


def test_m5_waarschuwing_bij_forwarded_for_zonder_proxy(app, client, klaar, caplog):
    from app.blueprints import auth

    auth._proxy_gewaarschuwd = False
    with caplog.at_level("WARNING"):
        client.post("/login", data={"gebruikersnaam": "x", "wachtwoord": "y"},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert "PROXY_VERTROUWEN" in caplog.text


# ---------------------------------------------------------------------------
# M7 · Wachtwoord wijzigen/resetten en deactiveren logt andere sessies niet uit
# M10 · Na terugzetten blijven sessies geldig op gebruikers-ID
# ---------------------------------------------------------------------------

def _uitgelogd(client) -> bool:
    """True als deze sessie naar het inlogscherm wordt gestuurd."""
    antwoord = client.get("/kalender/")
    return antwoord.status_code == 302 and "/login" in antwoord.headers["Location"]


def _twee_sessies(app, naam="beheerder"):
    from .conftest import login

    eerste, tweede = app.test_client(), app.test_client()
    login(eerste, naam)
    login(tweede, naam)
    assert eerste.get("/kalender/").status_code == 200 and tweede.get("/kalender/").status_code == 200
    return eerste, tweede


def test_m7_wachtwoord_wijzigen_logt_andere_sessie_uit(app, klaar):
    from .conftest import WACHTWOORD

    eerste, tweede = _twee_sessies(app)
    antwoord = eerste.post("/account/wachtwoord", data={
        "huidig": WACHTWOORD, "nieuw": "nieuwwachtwoord1", "herhaling": "nieuwwachtwoord1"})
    assert antwoord.status_code == 302
    assert eerste.get("/kalender/").status_code == 200  # wie wijzigde blijft ingelogd
    assert _uitgelogd(tweede)  # de andere sessie niet


def test_m7_reset_en_deactiveren_loggen_gebruiker_uit(app, klaar):
    from app.models import Gebruiker

    from .conftest import login

    beheerder = app.test_client()
    login(beheerder, "beheerder")
    collega, _ = _twee_sessies(app, "collega")
    gid = Gebruiker.query.filter_by(gebruikersnaam="collega").one().id
    beheerder.post(f"/beheer/gebruikers/{gid}/reset")
    assert _uitgelogd(collega)

    collega2 = app.test_client()
    db.session.get(Gebruiker, gid).moet_wachtwoord_wijzigen = False
    db.session.commit()
    login(collega2, "collega", "x")  # wachtwoord is nu onbekend: direct via de sessie testen
    gebruiker = db.session.get(Gebruiker, gid)
    with collega2.session_transaction() as sessie:
        sessie["_user_id"] = gebruiker.get_id()
        sessie["_fresh"] = True
    assert collega2.get("/kalender/").status_code == 200
    beheerder.post(f"/beheer/gebruikers/{gid}", data={
        "gebruikersnaam": "collega", "weergavenaam": "Collega", "rol": "gebruiker"})  # actief uit
    assert _uitgelogd(collega2)


def test_m7_oud_sessieformaat_is_ongeldig(app, klaar):
    client = app.test_client()
    with client.session_transaction() as sessie:
        sessie["_user_id"] = str(klaar["beheerder"].id)  # zoals vóór 1.2.0
        sessie["_fresh"] = True
    assert _uitgelogd(client)


def test_m10_terugzetten_logt_iedereen_uit(gemigreerd):
    from .conftest import login, maak_gebruiker

    maak_gebruiker("beheerder", "beheerder")
    maak_gebruiker("collega", "gebruiker")
    beheerder, collega = gemigreerd.test_client(), gemigreerd.test_client()
    login(beheerder, "beheerder")
    login(collega, "collega")
    beheerder.post("/beheer/backups/maken")
    naam = backup.lijst_backups()[0]["naam"]
    assert collega.get("/kalender/").status_code == 200
    antwoord = beheerder.post("/beheer/backups/terugzetten", data={"naam": naam, "bevestig": "1"})
    assert antwoord.status_code == 302
    assert _uitgelogd(collega) and _uitgelogd(beheerder)


# ---------------------------------------------------------------------------
# M8 · Optimistic locking was check-then-write (TOCTOU)
# ---------------------------------------------------------------------------

def test_m8_gelijktijdige_wijziging_geeft_conflict(app, mw, monkeypatch):
    from app.models import Dienst
    from app.services import weekrooster
    from app.services.weekrooster import VersieConflict, Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4")])
    dienst = Dienst.query.one()
    versie = dienst.versie
    echt = weekrooster._pas_veld_toe

    def met_tussenkomst(dienst, veld, waarde):
        # Precies tussen lezen en schrijven wijzigt een ander proces dezelfde dienst
        with db.engine.begin() as verbinding:
            verbinding.exec_driver_sql(
                "UPDATE dienst SET eind = '20:00', versie = versie + 1 WHERE id = ?", (dienst.id,))
        return echt(dienst, veld, waarde)

    monkeypatch.setattr(weekrooster, "_pas_veld_toe", met_tussenkomst)
    with pytest.raises(VersieConflict):
        wijzig_cellen([Wijziging(mw.id, MAANDAG, "eind", "17:00", versie=versie)])
    db.session.expire_all()
    assert Dienst.query.one().eind == "20:00"  # de wijziging van de ander blijft staan


def test_m8_conflict_via_api_geeft_409(app, als_beheerder, mw, monkeypatch):
    from app.models import Dienst
    from app.services import weekrooster
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4")])
    dienst_id = Dienst.query.one().id
    echt = weekrooster._pas_veld_toe

    def met_tussenkomst(dienst, veld, waarde):
        with db.engine.begin() as verbinding:
            verbinding.exec_driver_sql("UPDATE dienst SET versie = versie + 1 WHERE id = ?", (dienst_id,))
        return echt(dienst, veld, waarde)

    monkeypatch.setattr(weekrooster, "_pas_veld_toe", met_tussenkomst)
    antwoord = als_beheerder.post("/api/cellen", json={"opslaan": True, "wijzigingen": [
        {"mw": mw.id, "datum": MAANDAG.isoformat(), "veld": "eind", "waarde": "17:00", "versie": 1}]})
    assert antwoord.status_code == 409


# ---------------------------------------------------------------------------
# M9 · De Excel-import plande geen agenda-sync
# ---------------------------------------------------------------------------

def test_m9_import_plant_agenda_sync(app, klaar, tmp_path):
    from app.models import Medewerker, SyncTaak
    from app.services.excel_import import importeer, lees_bestand

    from .test_import_backup import maak_testbestand

    db.session.add(Medewerker(naam="Medewerker Vijf A", initialen="MVA", agenda_modus="B",
                              agenda_id="agenda-a"))
    db.session.commit()
    pad = str(tmp_path / "oud.xlsx")
    maak_testbestand(pad)
    importeer(lees_bestand(pad))
    taken = SyncTaak.query.all()
    assert [(t.soort, db.session.get(Medewerker, t.medewerker_id).naam) for t in taken] \
        == [("volledig", "Medewerker Vijf A")]
