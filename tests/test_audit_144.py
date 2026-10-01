"""Regressietests voor de bevindingen uit de audit van versie 1.4.4.

Elke test hoort bij één bevinding (H = high, M = medium, L = low, S = security).
De test faalde op de oude code en slaagt na de reparatie.
"""

from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import Dienst, Medewerker, SyncTaak

MAANDAG = date(2026, 3, 2)  # week 10 van 2026


@pytest.fixture
def mw(klaar):
    from app.services.voorbeeldpakket import laad_voorbeeldpakket

    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1)
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def _import_dienst(naam, dag, **extra):
    from app.services.excel_import import ImportDienst

    waarden = dict(naam=naam, datum=dag, code=None, dienstnaam="Cursus", begin="08:00",
                   eind="16:00", opmerking="", opm_begin=None, opm_eind=None, excel_uren=None)
    waarden.update(extra)
    return ImportDienst(**waarden)


def _wachtrij_nu():
    from app.services import sync

    SyncTaak.query.update({"niet_voor": datetime(2000, 1, 1)})
    db.session.commit()
    return sync.verwerk_wachtrij()


# ---------------------------------------------------------------------------
# H1 · De Excel-import wist diensten in weken die niet in het bestand staan
# ---------------------------------------------------------------------------

def test_h1_import_laat_weken_zonder_blad_ongemoeid(app, mw):
    from app.services.excel_import import ImportMedewerker, ImportPlan, importeer

    week12 = MAANDAG + timedelta(weeks=2)
    db.session.add(Dienst(medewerker_id=mw.id, datum=week12, dienstnaam_override="Blijft",
                          begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()
    plan = ImportPlan(jaar=2026, weken=[10, 14],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", MAANDAG),
                                _import_dienst("Medewerker A", MAANDAG + timedelta(weeks=4))])
    importeer(plan)
    assert Dienst.query.filter_by(datum=week12).one().dienstnaam_override == "Blijft"
    assert Dienst.query.count() == 3


def test_h1_droogloop_toont_te_verwijderen_bestaande_diensten(app, mw):
    from app.services.excel_import import ImportMedewerker, ImportPlan, effect

    for dag in (MAANDAG, MAANDAG + timedelta(days=1), MAANDAG + timedelta(weeks=2)):
        db.session.add(Dienst(medewerker_id=mw.id, datum=dag, dienstnaam_override="Oud",
                              begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()
    plan = ImportPlan(jaar=2026, weken=[10],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", MAANDAG)])
    per_mw = effect(plan).per_medewerker["Medewerker A"]
    # Maandag wordt vervangen, dinsdag verwijderd; week 12 (geen blad) telt niet mee
    assert (per_mw.nieuw, per_mw.vervangen, per_mw.verwijderd) == (0, 1, 1)


def test_h1_droogloopscherm_toont_verwijderde_diensten_per_medewerker(app, als_beheerder, tmp_path):
    import io

    from .test_import_backup import maak_testbestand

    medewerker = Medewerker(naam="Medewerker Vijf B", initialen="MVB")
    db.session.add(medewerker)
    db.session.commit()
    for dag in (MAANDAG + timedelta(days=1), MAANDAG + timedelta(days=2)):  # niet in het bestand
        db.session.add(Dienst(medewerker_id=medewerker.id, datum=dag, dienstnaam_override="Oud",
                              opmerking_tekst=""))
    db.session.commit()
    pad = str(tmp_path / "oud.xlsx")
    maak_testbestand(pad)
    with open(pad, "rb") as f:
        als_beheerder.post("/beheer/importeren", data={"bestand": (io.BytesIO(f.read()), "x.xlsx")},
                           content_type="multipart/form-data")
    pagina = als_beheerder.get("/beheer/importeren/voorbeeld").data.decode()
    rij = pagina.split("data-effect")[1].split("Medewerker Vijf B")[1].split("</tr>")[0]
    assert "<strong>2</strong>" in rij


# ---------------------------------------------------------------------------
# H2 · Dubbele Google-afspraken na een gedeeltelijk mislukte dag-sync
# ---------------------------------------------------------------------------

@pytest.fixture
def gekoppeld(mw):
    mw.agenda_modus, mw.agenda_id = "B", "agenda-a"
    db.session.commit()
    return mw


@pytest.fixture
def nep(app, monkeypatch):
    from app.services import google_agenda

    from .test_agenda import NepKlant

    klant = NepKlant()
    klant.agendas["agenda-a"] = {}
    monkeypatch.setattr(google_agenda, "klant", lambda: klant)
    return klant


def test_h2_tijdelijke_fout_bij_tweede_afspraak_geeft_geen_dubbele(app, gekoppeld, nep):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "17/3")])  # twee diensten
    nep.faal_bij = {"maak_afspraak": {2}}  # de tweede insert geeft een tijdelijke 503
    _wachtrij_nu()
    assert SyncTaak.query.one().pogingen == 1  # opnieuw proberen
    _wachtrij_nu()
    assert SyncTaak.query.count() == 0
    assert sorted(a["summary"] for a in nep.agendas["agenda-a"].values()) == ["BHV", "VW Avond"]
    ids = {d.google_event_id for d in Dienst.query.all()}
    assert len(ids) == 2 and ids == set(nep.agendas["agenda-a"])


def test_h2_mislukte_commit_na_insert_geeft_geen_dubbele(app, gekoppeld, nep, monkeypatch):
    """Google maakte de afspraak wel, maar het antwoord (of de commit) ging verloren."""
    from app.services import sync
    from app.services.google_agenda import AgendaFout
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    echt = nep.maak_afspraak

    def antwoord_kwijt(agenda_id, body):
        echt(agenda_id, body)
        raise AgendaFout("time-out", tijdelijk=True)

    monkeypatch.setattr(nep, "maak_afspraak", antwoord_kwijt)
    _wachtrij_nu()
    monkeypatch.setattr(nep, "maak_afspraak", echt)
    _wachtrij_nu()
    assert len(nep.agendas["agenda-a"]) == 1
    assert Dienst.query.one().google_event_id in nep.agendas["agenda-a"]
    assert sync.event_id_voor(Dienst.query.one()) == Dienst.query.one().google_event_id


def test_h2_event_id_is_geldig_voor_google(app, mw):
    import re

    from app.services import sync

    dienst = Dienst(id=12, medewerker_id=mw.id, datum=MAANDAG, volgnummer=2)
    event_id = sync.event_id_voor(dienst)
    assert re.fullmatch(r"[a-v0-9]{5,1024}", event_id)
    assert event_id == sync.event_id_voor(dienst)
    assert event_id != sync.event_id_voor(Dienst(medewerker_id=mw.id, datum=MAANDAG, volgnummer=1))


def test_h2_afspraak_opnieuw_na_verwijderen_werkt(app, gekoppeld, nep):
    """Na wissen en opnieuw invullen bestaat het ID al bij Google (geannuleerd): bijwerken."""
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    _wachtrij_nu()
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "")])
    _wachtrij_nu()
    assert nep.agendas["agenda-a"] == {} and Dienst.query.count() == 0
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "5")])
    _wachtrij_nu()
    assert SyncTaak.query.count() == 0
    assert [a["summary"] for a in nep.agendas["agenda-a"].values()] == ["VW Dag"]


# ---------------------------------------------------------------------------
# M1 · De worker verwijdert een dienst die de planner net opnieuw invulde
# ---------------------------------------------------------------------------

def _in_ander_proces(medewerker_id, datum, wijzig):
    """Wijzig een dienst via een eigen verbinding, zoals een webverzoek in een ander proces."""
    from sqlalchemy.orm import Session

    with Session(db.engine) as sessie:
        dienst = sessie.query(Dienst).filter_by(medewerker_id=medewerker_id, datum=datum).one()
        wijzig(dienst, sessie)
        dienst.versie += 1
        sessie.commit()


def test_m1_worker_verwijdert_opnieuw_ingevulde_dienst_niet(app, gekoppeld, nep, monkeypatch):
    from app.models import Dienstcode
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    _wachtrij_nu()
    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "")])  # leeg, afspraak moet weg
    code5 = Dienstcode.query.filter_by(nummer=5).one().id
    echt = nep.verwijder_afspraak

    def tussendoor(agenda_id, event_id):
        echt(agenda_id, event_id)

        def vul_in(dienst, sessie):  # de planner typt intussen code 5
            dienst.dienstcode_id, dienst.begin, dienst.eind = code5, "07:00", "15:30"

        _in_ander_proces(gekoppeld.id, MAANDAG, vul_in)

    monkeypatch.setattr(nep, "verwijder_afspraak", tussendoor)
    _wachtrij_nu()
    db.session.expire_all()
    dienst = Dienst.query.one()  # niet weggegooid
    assert dienst.dienstcode_id == code5
    monkeypatch.setattr(nep, "verwijder_afspraak", echt)
    from app.services import sync_planning

    sync_planning.plan_dag(dienst.medewerker, MAANDAG)
    _wachtrij_nu()
    assert [a["summary"] for a in nep.agendas["agenda-a"].values()] == ["VW Dag"]


def test_m1_worker_overschrijft_nieuwer_event_id_niet(app, gekoppeld, nep, monkeypatch):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(gekoppeld.id, MAANDAG, "code", "4")])
    echt = nep.maak_afspraak

    def tussendoor(agenda_id, body):
        event_id = echt(agenda_id, body)

        def ontkoppel(dienst, sessie):  # bijv. de planner past de dienst aan
            dienst.eind = "18:00"

        _in_ander_proces(gekoppeld.id, MAANDAG, ontkoppel)
        return event_id

    monkeypatch.setattr(nep, "maak_afspraak", tussendoor)
    _wachtrij_nu()
    db.session.expire_all()
    dienst = Dienst.query.one()
    assert dienst.eind == "18:00" and dienst.versie == 2


# ---------------------------------------------------------------------------
# M2 · Een vrije dienstnaam van dienst 2 verdwijnt via het coderaster
# ---------------------------------------------------------------------------

def _dag(mw_id):
    from app.services.weekrooster import diensten_van_dag

    db.session.expire_all()
    return diensten_van_dag(mw_id, MAANDAG)


def test_m2_vrije_tweede_dienst_blijft_bij_andere_eerste_code(app, mw):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4/3")])
    wijzig_cellen([Wijziging(mw.id, MAANDAG, "dienstnaam", "Cursus", volgnummer=2)])
    d1, d2 = _dag(mw.id)
    from app.services.weekrooster import matrix_code

    assert matrix_code(d1, d2) == "4/"  # het raster toont de vrije naam niet als code
    bijgewerkt, fouten = wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "5/")])
    assert fouten == []
    d1, d2 = _dag(mw.id)
    assert d1.dienstcode.nummer == 5 and d2 is not None and d2.dienstnaam == "Cursus"
    assert bijgewerkt[f"{mw.id}|{MAANDAG.isoformat()}"]["code"] == "5/"


def test_m2_zonder_tweede_deel_verdwijnt_dienst2_wel(app, mw):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4/3")])
    wijzig_cellen([Wijziging(mw.id, MAANDAG, "dienstnaam", "Cursus", volgnummer=2)])
    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "5")])
    d1, d2 = _dag(mw.id)
    assert d1.dienstcode.nummer == 5 and d2 is None


def test_m2_lege_tweede_code_wist_een_tweede_dienst_met_code(app, mw):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4/3")])
    wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4/")])
    d1, d2 = _dag(mw.id)
    assert d1.dienstcode.nummer == 4 and d2 is None


# ---------------------------------------------------------------------------
# M3 · De worker draait als PID 1 zonder SIGTERM-handler
# ---------------------------------------------------------------------------

def test_m3_worker_stopt_netjes_na_sigterm(app, klaar, monkeypatch):
    import os
    import signal

    from app import worker

    rondes = []

    def ronde(planning, nu=None):
        rondes.append(1)
        os.kill(os.getpid(), signal.SIGTERM)  # 'docker stop' midden in een ronde

    monkeypatch.setattr(worker, "create_app", lambda: app)
    monkeypatch.setattr(worker, "een_ronde", ronde)
    oud = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        worker.main()  # moet na de lopende ronde zelf stoppen (geen oneindige lus)
    finally:
        for sig, handler in oud.items():
            signal.signal(sig, handler)
    assert rondes == [1]


@pytest.mark.parametrize("bestand", ["docker-compose.yml", "README.md"])
def test_m3_init_in_docker_compose(bestand):
    """Een kleine init (tini) als PID 1 geeft signalen door en ruimt zombieprocessen op."""
    import os
    import re

    with open(os.path.join(os.path.dirname(__file__), "..", bestand), encoding="utf-8") as f:
        tekst = f.read()
    for service in ("web", "worker"):
        blok = re.search(rf"^  {service}:\n((?:    .*\n|\n)+)", tekst, re.M)
        assert blok and re.search(r"^    init: true", blok.group(1), re.M), service


# ---------------------------------------------------------------------------
# M4 · Na het terugzetten van een back-up worden de agenda's niet bijgewerkt
# ---------------------------------------------------------------------------

def _gekoppelde_backup():
    from app.services import backup, instellingen

    instellingen.schrijf("setup_voltooid", "1")
    db.session.add_all([Medewerker(naam="Medewerker A", initialen="MA", agenda_modus="B",
                                   agenda_id="agenda-a"),
                        Medewerker(naam="Medewerker B", initialen="MB")])
    db.session.commit()
    return backup.maak_backup("handmatig")


def test_m4_terugzetten_via_scherm_plant_agenda_sync(gemigreerd, client):
    import os

    from .conftest import login, maak_gebruiker

    pad = _gekoppelde_backup()
    maak_gebruiker("beheerder", "beheerder")
    login(client, "beheerder")
    antwoord = client.post("/beheer/backups/terugzetten",
                           data={"naam": os.path.basename(pad), "bevestig": "1"}, follow_redirects=True)
    db.session.remove()
    taken = SyncTaak.query.all()
    assert [(t.soort, t.medewerker_id) for t in taken] == \
        [("volledig", Medewerker.query.filter_by(initialen="MA").one().id)]
    assert "Google Agenda" in antwoord.data.decode()


def test_m4_terugzetten_via_cli_plant_agenda_sync(gemigreerd):
    import os

    pad = _gekoppelde_backup()
    resultaat = gemigreerd.test_cli_runner().invoke(args=["terugzetten", os.path.basename(pad), "--yes"])
    assert resultaat.exit_code == 0, resultaat.output
    db.session.remove()
    assert [t.soort for t in SyncTaak.query.all()] == ["volledig"]
    assert "Google Agenda" in resultaat.output


# ---------------------------------------------------------------------------
# M5 · Inlogvloed: per nieuwe naam elke poging argon2 en databaserijen
# ---------------------------------------------------------------------------

def _mislukte_pogingen_vanaf_ip(aantal, ip="127.0.0.1"):
    from app.models import LoginPoging
    from app.services import klok

    db.session.add_all([LoginPoging(gebruikersnaam=f"onbekend{i}", ip=ip, gelukt=False,
                                    tijdstip=klok.utc_nu()) for i in range(aantal)])
    db.session.commit()


def _tel_rijen():
    from app.models import Logboek, LoginPoging

    return LoginPoging.query.count(), Logboek.query.count()


def test_m5_harde_grens_per_ip_zonder_hash_en_zonder_rijen(app, client, klaar, monkeypatch):
    from app.blueprints import auth

    hashes = []
    monkeypatch.setattr(auth, "controleer_dummy", lambda w: hashes.append(w) or False)
    monkeypatch.setattr(auth, "controleer_wachtwoord", lambda h, w: hashes.append(w) or False)
    _mislukte_pogingen_vanaf_ip(auth.HARDE_GRENS_PER_IP)
    client.post("/login", data={"gebruikersnaam": "nieuw1", "wachtwoord": "x"})  # eerste: één logregel
    voor = _tel_rijen()
    for i in range(5):
        antwoord = client.post("/login", data={"gebruikersnaam": f"nieuwer{i}", "wachtwoord": "x"})
        assert antwoord.status_code == 429
    assert hashes == []  # geen argon2 meer
    assert _tel_rijen() == voor  # geen nieuwe pogingen of logboekregels


def test_m5_tijdens_blokkade_geen_login_mislukt_regels(app, client, klaar):
    from app.blueprints import auth
    from app.models import Logboek

    _mislukte_pogingen_vanaf_ip(auth.MAX_POGINGEN_PER_IP)
    for i in range(3):
        client.post("/login", data={"gebruikersnaam": f"naam{i}", "wachtwoord": "fout"})
    assert Logboek.query.filter_by(actie="Login mislukt").count() == 0


def test_m5_een_kans_per_naam_blijft_tot_de_harde_grens(app, client, klaar):
    from app.blueprints import auth

    from .conftest import login

    _mislukte_pogingen_vanaf_ip(auth.HARDE_GRENS_PER_IP - 1)
    assert login(client, "collega").status_code == 302
