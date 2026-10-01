"""App-opstart, foutpagina's, inloggen en kleine routes: randgevallen. Alle data is fictief."""

import os

import pytest

from app import create_app
from app.extensions import db
from app.models import Dienstcode, Gebruiker, Medewerker
from app.services import instellingen
from app.services.voorbeeldpakket import laad_voorbeeldpakket

from .conftest import WACHTWOORD, TestConfig, login

# ---------------------------------------------------------------------------
# Opstart: geheime sleutel en reverse proxy
# ---------------------------------------------------------------------------


def test_geheime_sleutel_wordt_gemaakt_en_hergebruikt(tmp_path):
    config = TestConfig(str(tmp_path))
    config.SECRET_KEY = ""
    eerste = create_app(config).config["SECRET_KEY"]
    pad = tmp_path / "secret_key"
    assert len(eerste) == 64 and pad.read_text().strip() == eerste
    assert oct(os.stat(pad).st_mode & 0o777) == "0o600"
    assert create_app(config).config["SECRET_KEY"] == eerste  # tweede start: zelfde sleutel
    pad.write_text("\n")  # leeg bestand: nieuwe sleutel
    assert create_app(config).config["SECRET_KEY"] not in ("", eerste)


def test_proxy_vertrouwen_zet_proxyfix(tmp_path):
    from werkzeug.middleware.proxy_fix import ProxyFix

    config = TestConfig(str(tmp_path))
    config.PROXY_VERTROUWEN = True
    assert isinstance(create_app(config).wsgi_app, ProxyFix)


# ---------------------------------------------------------------------------
# Foutpagina's en gezondheid
# ---------------------------------------------------------------------------

def test_api_fouten_in_json(app, client, klaar):
    from flask import abort

    @app.route("/api/v1/test-verboden")
    def _verboden():
        abort(403)

    assert client.get("/api/v1/bestaat-niet").get_json() == {"fout": "Niet gevonden."}
    antwoord = client.get("/api/v1/test-verboden")
    assert antwoord.status_code == 403 and antwoord.is_json


def test_405_buiten_de_api_is_gewone_fout(app, als_beheerder):
    assert als_beheerder.post("/health").status_code == 405


def test_500_buiten_de_api_geeft_foutpagina(app, als_beheerder, monkeypatch):
    from app.blueprints import zoeken

    monkeypatch.setattr(zoeken.Dienstcode, "query", property(lambda _self: 1 / 0), raising=False)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    monkeypatch.setattr(zoeken, "render_template", lambda *a, **k: 1 / 0)
    antwoord = als_beheerder.get("/zoeken/")
    assert antwoord.status_code == 500 and "Er ging iets mis op de server" in antwoord.data.decode()


def test_health_meldt_databasefout(app, client, monkeypatch):
    def kapot(*_args, **_kwargs):
        raise RuntimeError("database weg")

    monkeypatch.setattr(db.session, "execute", kapot)
    antwoord = client.get("/health")
    assert antwoord.status_code == 503 and antwoord.get_json() == {"status": "fout"}


def test_teamnaam_als_database_nog_leeg_is(tmp_path):
    app = create_app(TestConfig(str(tmp_path)))  # geen tabellen: eerste start
    with app.test_request_context("/"):
        variabelen = {}
        for functie in app.template_context_processors[None]:
            variabelen.update(functie())
        assert variabelen["teamnaam"] == "Beveiligingsrooster"
    with app.test_request_context("/manifest.webmanifest"):
        antwoord = app.view_functions["pwa.manifest"]()
        assert antwoord.get_json()["name"]


def test_startpagina_beheerder_naar_kalender(app, als_beheerder):
    assert "/kalender" in als_beheerder.get("/").headers["Location"]


# ---------------------------------------------------------------------------
# Inloggen, uitloggen, wachtwoord
# ---------------------------------------------------------------------------

def test_login_volgende_binnen_de_site(app, client, klaar):
    antwoord = client.post("/login?volgende=/zoeken/", data={"gebruikersnaam": "collega",
                                                              "wachtwoord": WACHTWOORD})
    assert antwoord.headers["Location"] == "/zoeken/"


def test_login_herhasht_oud_wachtwoord(app, client, klaar, monkeypatch):
    from app.blueprints import auth

    oud = db.session.get(Gebruiker, klaar["gebruiker"].id).wachtwoord_hash
    monkeypatch.setattr(auth, "moet_opnieuw_hashen", lambda _hash: True)
    login(client, "collega")
    db.session.expire_all()
    assert db.session.get(Gebruiker, klaar["gebruiker"].id).wachtwoord_hash != oud


def test_uitloggen_zonder_sessie(app, client, klaar):
    assert client.post("/uitloggen").status_code == 302


def test_wachtwoord_wijzigen_fouten(app, als_gebruiker):
    assert als_gebruiker.get("/account/wachtwoord").status_code == 200
    for data, melding in (({"huidig": "fout", "nieuw": "x", "herhaling": "x"},
                           "huidige wachtwoord klopt niet"),
                          ({"huidig": WACHTWOORD, "nieuw": "kort", "herhaling": "kort"}, "tekens"),
                          ({"huidig": WACHTWOORD, "nieuw": WACHTWOORD, "herhaling": WACHTWOORD},
                           "ander wachtwoord")):
        antwoord = als_gebruiker.post("/account/wachtwoord", data=data)
        assert melding in antwoord.data.decode(), data


# ---------------------------------------------------------------------------
# API, deellink, ICS, rooster
# ---------------------------------------------------------------------------

def test_api_eerst_wachtwoord_wijzigen_en_datum_buiten_bereik(app, klaar):
    from .test_api import bearer, maak_token

    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.flush()
    db.session.get(Gebruiker, klaar["gebruiker"].id).medewerker_id = medewerker.id
    db.session.commit()
    client = app.test_client()
    token = maak_token(client)
    antwoord = client.get("/api/v1/mijn-rooster?van=1900-01-01", headers=bearer(token))
    assert antwoord.status_code == 400 and "buiten" in antwoord.get_json()["fout"]
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.moet_wachtwoord_wijzigen = True
    db.session.commit()
    antwoord = app.test_client().get("/api/v1/ik", headers=bearer(token))
    assert antwoord.status_code == 403 and "nieuw wachtwoord" in antwoord.get_json()["fout"]


def test_deellink_ongeldige_week_en_ics_kort_token(app, client, klaar):
    instellingen.schrijf("deellink_actief", "1")
    instellingen.schrijf("deellink_token", "t" * 32)
    db.session.commit()
    assert client.get(f"/deel/{'t' * 32}/week/2026/60").status_code == 404
    assert client.get("/ics/kort.ics").status_code == 404


def test_hulp_getal_ongeldig():
    from app.blueprints.hulp import getal

    assert getal("12abc") is None and getal("inf") is None and getal("1,5") == 1.5


@pytest.fixture
def mw(klaar):
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def test_rooster_routes_randgevallen(app, als_beheerder, mw):
    assert "/week/" in als_beheerder.get("/week?dag=onzin").headers["Location"]
    assert als_beheerder.post("/week/2026/60/kopieer", data={"naar": "2026-W11"}).status_code == 404
    antwoord = als_beheerder.post("/api/cellen", data="geen json", content_type="text/plain")
    assert antwoord.status_code == 200  # leeg verzoek: niets te doen
    for item in ({"mw": mw.id, "datum": "2026-03-02", "veld": "onbekend", "waarde": "x"},
                 {"mw": [1], "datum": "2026-03-02", "veld": "code", "waarde": "4"}):
        antwoord = als_beheerder.post("/api/cellen", json={"wijzigingen": [item]})
        assert antwoord.status_code == 400, item


def test_mijn_rooster_zonder_gekoppelde_medewerker(app, als_gebruiker):
    for url in ("/mijn", "/mijn/agenda"):
        antwoord = als_gebruiker.get(url, follow_redirects=True)
        assert "niet gekoppeld aan een medewerker" in antwoord.data.decode(), url


def test_zoeken_zonder_filters(app, als_gebruiker):
    assert als_gebruiker.get("/zoeken/").status_code == 200
    assert Dienstcode.query.count() == 0
