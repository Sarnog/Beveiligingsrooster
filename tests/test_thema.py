"""Schakelaar licht/donker: per gebruiker opgeslagen, dus ook na opnieuw inloggen."""

from app.extensions import db
from app.models import Gebruiker

from .conftest import login


def _thema(gebruikersnaam: str) -> str | None:
    db.session.expire_all()
    return Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).one().thema


def test_schakelaar_staat_in_het_menu(als_gebruiker):
    pagina = als_gebruiker.get("/account/tokens").get_data(as_text=True)
    assert "data-thema-wissel" in pagina and "thema-schakelaar" in pagina
    assert "data-thema=" not in pagina.split("<head>")[0]  # nog geen keuze: volg het apparaat


def test_thema_kiezen_en_bewaren_na_opnieuw_inloggen(client, klaar):
    login(client, "collega")
    antwoord = client.post("/account/thema", data={"thema": "donker", "volgende": "/account/tokens?"})
    assert antwoord.status_code == 302 and antwoord.headers["Location"].endswith("/account/tokens")
    assert _thema("collega") == "donker"

    client.post("/uitloggen")
    login(client, "collega")
    pagina = client.get("/account/tokens").get_data(as_text=True)
    assert '<html lang="nl" data-thema="donker">' in pagina

    client.post("/account/thema", data={"thema": "licht"})
    assert _thema("collega") == "licht"
    assert _thema("beheerder") is None  # elke gebruiker heeft een eigen keuze


def test_zonder_keuze_wisselt_de_server(als_gebruiker):
    als_gebruiker.post("/account/thema")
    assert _thema("collega") == "donker"
    als_gebruiker.post("/account/thema", data={"thema": "onzin"})
    assert _thema("collega") == "licht"


def test_alleen_doorsturen_binnen_de_site(als_gebruiker):
    antwoord = als_gebruiker.post("/account/thema", data={"thema": "donker", "volgende": "//elders.nl/"})
    assert "elders.nl" not in antwoord.headers["Location"]


def test_niet_ingelogd_geen_thema(client, klaar):
    assert client.post("/account/thema", data={"thema": "donker"}).status_code == 401
