"""Debuglog: instelbaar logniveau, optioneel logbestand in data/logs, beheerscherm."""

import logging
import os

import pytest

from app import create_app, debuglog
from app.extensions import db

from . import conftest
from .conftest import login


@pytest.fixture
def debug_app(tmp_path, monkeypatch):
    """App met DEBUG_LOG=1; ruimt de handlers na afloop weer op."""
    monkeypatch.setenv("DEBUG_LOG", "1")
    monkeypatch.setenv("LOG_NIVEAU", "INFO")
    app = create_app(conftest.TestConfig(str(tmp_path)))
    from .conftest import _vergeet_ingelogde_gebruiker

    app.before_request_funcs.setdefault(None, []).insert(0, _vergeet_ingelogde_gebruiker)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
    debuglog.verwijder_handlers()


def _inhoud(app) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    with open(debuglog.bestand(app.config["DATA_MAP"]), encoding="utf-8") as bestand:
        return bestand.read()


def test_zonder_debug_log_geen_bestand(app):
    assert not os.path.exists(debuglog.bestand(app.config["DATA_MAP"]))
    assert not app.config["DEBUG_LOG"] and app.config["LOG_NIVEAU"] == "INFO"


def test_ongeldig_niveau_wordt_info(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_NIVEAU", "praatgraag")
    assert conftest.TestConfig(str(tmp_path)).LOG_NIVEAU == "INFO"
    monkeypatch.setenv("LOG_NIVEAU", "debug")
    assert conftest.TestConfig(str(tmp_path)).LOG_NIVEAU == "DEBUG"


def test_debug_regels_in_bestand_zonder_geheimen(debug_app):
    from app.services import instellingen

    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    client = debug_app.test_client()
    client.post("/login", data={"gebruikersnaam": "iemand", "wachtwoord": "Supergeheim-123"})
    client.get("/ics/eengeheimtokenvanvoldoendelengte.ics")
    tekst = _inhoud(debug_app)
    assert "DEBUG" in tekst and "Login mislukt" in tekst  # debugregels komen in het bestand
    assert "POST /login" in tekst and "/ics/***" in tekst  # verzoeken, met gemaskeerd token
    assert "Supergeheim-123" not in tekst and "eengeheimtoken" not in tekst
    assert "sqlalchemy.engine" not in tekst and "argon2" not in tekst  # geen SQL of hashes


def test_console_volgt_log_niveau(debug_app):
    console = [h for h in logging.getLogger().handlers if getattr(h, "_rooster", "") == "console"]
    assert console and console[0].level == logging.INFO
    assert logging.getLogger().level == logging.DEBUG  # het bestand krijgt alles


def test_rotatie(debug_app, monkeypatch):
    pad = debuglog.bestand(debug_app.config["DATA_MAP"])
    monkeypatch.setattr(debuglog, "MAX_BYTES", 100)
    for _ in range(5):
        logging.getLogger("test").debug("x" * 200)
        assert debuglog.roteer(debug_app.config["DATA_MAP"]) is True
    logging.getLogger("test").debug("na de rotatie")
    assert "na de rotatie" in _inhoud(debug_app)  # de handler opent het nieuwe bestand
    namen = sorted(os.listdir(os.path.dirname(pad)))
    assert namen == ["debug.log", "debug.log.1", "debug.log.2", "debug.log.3"]
    assert debuglog.roteer(debug_app.config["DATA_MAP"]) is False  # nog klein genoeg


def test_worker_roteert(debug_app, monkeypatch):
    from app import worker

    aanroepen = []
    monkeypatch.setattr(debuglog, "roteer", lambda map_: aanroepen.append(map_) or False)
    worker.een_ronde(worker.Planning())
    assert aanroepen == [debug_app.config["DATA_MAP"]]


def test_beheerscherm(debug_app):
    from app.services import instellingen

    from .conftest import maak_gebruiker

    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    maak_gebruiker("beheerder", "beheerder")
    maak_gebruiker("collega", "gebruiker")
    logging.getLogger("test").debug("een regel <script>alert(1)</script>")
    beheerder = debug_app.test_client()
    login(beheerder, "beheerder")
    pagina = beheerder.get("/beheer/debuglog").data.decode()
    assert "een regel" in pagina and "<script>alert" not in pagina  # netjes ge-escaped
    download = beheerder.get("/beheer/debuglog/download")
    assert download.status_code == 200 and b"een regel" in download.data
    collega = debug_app.test_client()
    login(collega, "collega")
    assert collega.get("/beheer/debuglog").status_code == 403


def test_beheerscherm_zonder_debug_log_legt_uit(app, als_beheerder):
    pagina = als_beheerder.get("/beheer/debuglog").data.decode()
    assert "Het debuglog-bestand staat uit" in pagina and "Volgens .env (INFO)" in pagina
    assert als_beheerder.get("/beheer/debuglog/download").status_code == 404


def test_logniveau_en_debuglog_via_beheer(app, als_beheerder):
    """Zonder .env aan te passen: DEBUG en het logbestand aan, en weer terug naar .env."""
    from app.models import Logboek

    try:
        antwoord = als_beheerder.post("/beheer/debuglog/instellen",
                                      data={"log_niveau": "DEBUG", "debug_log": "1"}, follow_redirects=True)
        assert "Loginstelling opgeslagen" in antwoord.data.decode()
        console = [h for h in logging.getLogger().handlers if getattr(h, "_rooster", "") == "console"]
        assert console[0].level == logging.DEBUG
        assert (debuglog.stand(app)["niveau"], debuglog.stand(app)["aan"]) == ("DEBUG", True)
        logging.getLogger("test").debug("via beheer aangezet")
        assert "via beheer aangezet" in _inhoud(app)
        pagina = als_beheerder.get("/beheer/debuglog").data.decode()
        assert "Download debug.log" in pagina and "via beheer aangezet" in pagina
        regel = Logboek.query.filter_by(actie="Loginstelling gewijzigd").first()
        assert regel.nieuwe_waarde == "DEBUG, debuglog aan"

        # Een ander proces (bijv. de worker) pikt het op bij ververs()
        debuglog.stel_in(app)
        debuglog.ververs(app, direct=True)
        assert debuglog.stand(app)["niveau"] == "DEBUG" and debuglog.stand(app)["aan"]

        # Terug naar .env: INFO en geen logbestand meer
        als_beheerder.post("/beheer/debuglog/instellen", data={"log_niveau": "", "debug_log": ""})
        assert console[0].level == logging.INFO
        assert not [h for h in logging.getLogger().handlers if getattr(h, "_rooster", "") == "bestand"]
        assert als_beheerder.post("/beheer/debuglog/instellen",
                                  data={"log_niveau": "PRAATGRAAG"}).status_code == 302
        assert debuglog.effectief(app) == ("INFO", False)  # ongeldige keuze niet opgeslagen
    finally:
        debuglog.verwijder_handlers()


def test_gunicorn_volgt_log_niveau(monkeypatch):
    import runpy

    monkeypatch.setenv("LOG_NIVEAU", "DEBUG")
    pad = os.path.join(os.path.dirname(__file__), "..", "docker", "gunicorn.conf.py")
    assert runpy.run_path(pad)["loglevel"] == "debug"
