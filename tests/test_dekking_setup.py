"""Setup-wizard: navigatie en randgevallen. Alle data is fictief."""

from app.extensions import db
from app.models import Medewerker
from app.services import setup_code

from .conftest import WACHTWOORD, login, maak_gebruiker


def _met_code(client):
    client.get("/setup/")
    assert client.post("/setup/", data={"code": setup_code.lees_code()}).status_code == 302


def test_setup_navigatie_en_lege_formulieren(app, client):
    _met_code(client)
    assert client.get("/setup/").headers["Location"].endswith("/setup/stap/1")  # code al goed
    assert client.get("/setup/stap/0").status_code == 404
    assert client.get("/setup/stap/6").status_code == 404
    assert client.get("/setup/stap/2").headers["Location"].endswith("/setup/stap/1")  # nog niet ingelogd
    assert "stap" in client.get("/setup/stap/1").data.decode()
    antwoord = client.post("/setup/stap/1", data={"gebruikersnaam": "", "weergavenaam": ""})
    assert antwoord.status_code == 400
    assert "Vul een gebruikersnaam en weergavenaam in" in antwoord.data.decode()
    client.post("/setup/stap/1", data={"gebruikersnaam": "planner", "weergavenaam": "Planner",
                                       "wachtwoord": WACHTWOORD, "herhaling": WACHTWOORD})
    # Ingelogd als beheerder: stap 1 gaat door naar stap 2
    assert client.get("/setup/stap/1").headers["Location"].endswith("/setup/stap/2")
    for stap in (2, 3, 4, 5):
        assert client.get(f"/setup/stap/{stap}").status_code == 200, stap
    assert client.post("/setup/stap/3", data={"keuze": "leeg"}).headers["Location"].endswith("/setup/stap/4")
    assert client.post("/setup/stap/4", data={"overslaan": "1"}).headers["Location"].endswith("/setup/stap/5")
    assert client.post("/setup/stap/4", data={"medewerkers": ""}).status_code == 302
    assert Medewerker.query.count() == 0


def test_setup_medewerkers_zonder_bruikbare_initialen(app, client):
    _met_code(client)
    client.post("/setup/stap/1", data={"gebruikersnaam": "planner", "weergavenaam": "Planner",
                                       "wachtwoord": WACHTWOORD, "herhaling": WACHTWOORD})
    client.post("/setup/stap/4", data={"medewerkers": "  ;40\n???\nMedewerker A"})
    assert sorted(m.initialen for m in Medewerker.query.all())[0] == "M1"
    assert Medewerker.query.count() == 2


def test_setup_stap1_met_bestaande_beheerder_vraagt_inloggen(app, client):
    maak_gebruiker("planner", "beheerder")
    _met_code(client)
    antwoord = client.get("/setup/stap/1")
    assert "/login" in antwoord.headers["Location"]
    login(client, "planner")
    db.session.expire_all()
    assert client.get("/setup/stap/1").headers["Location"].endswith("/setup/stap/2")
