"""Setup-wizard, inloggen, blokkade, wachtwoord wijzigen, laatste beheerder."""

import os

from app.extensions import db
from app.models import Dienstcode, Gebruiker, Logboek, Medewerker
from app.services import instellingen, setup_code

from .conftest import WACHTWOORD, login


def test_zonder_setup_alles_naar_setup(client):
    antwoord = client.get("/beheer/")
    assert antwoord.status_code == 302 and antwoord.headers["Location"].endswith("/setup/")
    assert client.get("/health").status_code == 200


def test_volledige_setup(app, client):
    client.get("/setup/")  # maakt de code aan
    code = setup_code.lees_code()
    assert code

    # Verkeerde code
    assert client.post("/setup/", data={"code": "FOUT"}).status_code == 400
    # Stap 1 kan niet zonder code
    assert client.get("/setup/stap/1").status_code == 302

    assert client.post("/setup/", data={"code": code.lower()}).status_code == 302
    # Te kort wachtwoord
    antwoord = client.post("/setup/stap/1", data={
        "gebruikersnaam": "planner", "weergavenaam": "Planner", "wachtwoord": "kort",
        "herhaling": "kort"})
    assert antwoord.status_code == 400
    antwoord = client.post("/setup/stap/1", data={
        "gebruikersnaam": "Planner", "weergavenaam": "Planner", "wachtwoord": WACHTWOORD,
        "herhaling": WACHTWOORD})
    assert antwoord.headers["Location"].endswith("/setup/stap/2")
    assert Gebruiker.query.filter_by(gebruikersnaam="planner").one().is_beheerder

    client.post("/setup/stap/2", data={
        "teamnaam": "Team Test", "tijdzone": "Europe/Amsterdam", "eerste_jaar": "2026",
        "toeslag_zaterdag": "1,5", "toeslag_zondag": "2", "logboek_dagen": "31", "logboek_uren": "0"})
    assert instellingen.lees("teamnaam") == "Team Test"

    client.post("/setup/stap/3", data={"keuze": "voorbeeld"})
    assert Dienstcode.query.count() == 18
    assert Dienstcode.query.filter_by(nummer=15).first() is None  # blanco-code

    client.post("/setup/stap/4", data={"medewerkers": "Medewerker A;1659\nMedewerker B"})
    assert Medewerker.query.count() == 2
    assert Medewerker.query.filter_by(naam="Medewerker A").one().contracturen_voor(2026) == 1659

    antwoord = client.post("/setup/stap/5")
    assert antwoord.status_code == 302
    assert instellingen.setup_voltooid()
    assert setup_code.lees_code() is None
    assert not os.path.exists(os.path.join(app.config["DATA_MAP"], "setup-code.txt"))
    # /setup bestaat daarna niet meer
    assert client.get("/setup/").status_code == 404
    assert client.get("/setup/stap/1").status_code == 404


def test_login_en_uitloggen(client, klaar):
    antwoord = login(client, "beheerder")
    assert antwoord.status_code == 302
    assert client.get("/beheer/").status_code == 200
    client.post("/uitloggen")
    assert client.get("/beheer/").status_code == 302
    acties = [r.actie for r in Logboek.query.all()]
    assert "Login" in acties and "Uitloggen" in acties


def test_mislukte_login_wordt_gelogd(client, klaar):
    assert login(client, "beheerder", "verkeerd-wachtwoord").status_code == 401
    assert Logboek.query.filter_by(actie="Login mislukt").count() == 1


def test_blokkade_na_vijf_pogingen(client, klaar):
    for _ in range(5):
        login(client, "beheerder", "verkeerd-wachtwoord")
    # Ook met het goede wachtwoord nu geblokkeerd
    assert login(client, "beheerder").status_code == 429


def test_open_redirect_niet_mogelijk(client, klaar):
    antwoord = client.post("/login?volgende=https://kwaadaardig.voorbeeld/",
                           data={"gebruikersnaam": "beheerder", "wachtwoord": WACHTWOORD})
    assert "kwaadaardig" not in antwoord.headers["Location"]


def test_wachtwoord_moet_gewijzigd_na_reset(client, klaar):
    gebruiker = klaar["gebruiker"]
    gebruiker.moet_wachtwoord_wijzigen = True
    db.session.commit()
    login(client, "collega")
    antwoord = client.get("/")
    assert antwoord.headers["Location"].endswith("/account/wachtwoord")
    client.post("/account/wachtwoord", data={
        "huidig": WACHTWOORD, "nieuw": "nieuwwachtwoord1", "herhaling": "nieuwwachtwoord1"})
    assert not db.session.get(Gebruiker, gebruiker.id).moet_wachtwoord_wijzigen


def test_laatste_beheerder_beschermd(als_beheerder, klaar):
    beheerder = klaar["beheerder"]
    # Degraderen naar gebruiker mag niet
    antwoord = als_beheerder.post(f"/beheer/gebruikers/{beheerder.id}", data={
        "gebruikersnaam": "beheerder", "weergavenaam": "B", "rol": "gebruiker", "actief": "1"})
    assert antwoord.status_code == 400
    assert db.session.get(Gebruiker, beheerder.id).is_beheerder
    # Eigen account verwijderen mag niet
    als_beheerder.post(f"/beheer/gebruikers/{beheerder.id}/verwijder")
    assert db.session.get(Gebruiker, beheerder.id) is not None


def test_nieuw_account_moet_wachtwoord_wijzigen(als_beheerder):
    als_beheerder.post("/beheer/gebruikers/nieuw", data={
        "gebruikersnaam": "nieuwe.collega", "weergavenaam": "Nieuwe collega", "rol": "gebruiker",
        "wachtwoord": "tijdelijk12345", "actief": "1"})
    nieuw = Gebruiker.query.filter_by(gebruikersnaam="nieuwe.collega").one()
    assert nieuw.moet_wachtwoord_wijzigen and not nieuw.is_beheerder


def test_security_headers(client, klaar):
    antwoord = client.get("/login")
    assert "default-src 'self'" in antwoord.headers["Content-Security-Policy"]
    assert antwoord.headers["X-Frame-Options"] == "DENY"


def test_csrf_verplicht(app, klaar):
    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    antwoord = client.post("/login", data={"gebruikersnaam": "beheerder", "wachtwoord": WACHTWOORD})
    assert antwoord.status_code == 400
