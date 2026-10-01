"""Tests met CSRF-bescherming aan, zoals in productie.

Het token wordt uit de meta-tag van de pagina gehaald, net als app.js dat doet.
"""

import re
from datetime import date

import pytest

from app.extensions import db
from app.models import Dienst, Medewerker
from app.services.voorbeeldpakket import laad_voorbeeldpakket

from .conftest import WACHTWOORD

TOKEN = re.compile(r'<meta name="csrf-token" content="([^"]+)">')


@pytest.fixture
def csrf_client(app, klaar):
    app.config["WTF_CSRF_ENABLED"] = True
    return app.test_client()


def token(client, pad="/login") -> str:
    """Het CSRF-token uit de meta-tag van een pagina."""
    gevonden = TOKEN.search(client.get(pad).data.decode())
    assert gevonden, f"geen csrf-token op {pad}"
    return gevonden.group(1)


def inloggen(client) -> None:
    antwoord = client.post("/login", data={"gebruikersnaam": "beheerder", "wachtwoord": WACHTWOORD,
                                           "csrf_token": token(client)})
    assert antwoord.status_code == 302


def test_login_zonder_token_geweigerd(csrf_client):
    antwoord = csrf_client.post("/login", data={"gebruikersnaam": "beheerder", "wachtwoord": WACHTWOORD})
    assert antwoord.status_code == 400


def test_login_met_token(csrf_client):
    inloggen(csrf_client)
    assert csrf_client.get("/beheer/").status_code == 200


def test_login_met_verkeerd_token(csrf_client):
    token(csrf_client)
    antwoord = csrf_client.post("/login", data={"gebruikersnaam": "beheerder", "wachtwoord": WACHTWOORD,
                                                "csrf_token": "verzonnen"})
    assert antwoord.status_code == 400


def test_formulier_post(csrf_client):
    inloggen(csrf_client)
    gegevens = {"naam": "Herfstvakantie", "datum_van": "2026-10-19", "datum_tot": "2026-10-23"}
    assert csrf_client.post("/beheer/vakanties/opslaan", data=gegevens).status_code == 400
    gegevens["csrf_token"] = token(csrf_client, "/beheer/vakanties")
    assert csrf_client.post("/beheer/vakanties/opslaan", data=gegevens).status_code == 302


def test_api_cellen_met_en_zonder_token(csrf_client):
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.commit()
    inloggen(csrf_client)
    body = {"opslaan": True, "wijzigingen": [
        {"mw": medewerker.id, "datum": "2026-03-02", "veld": "code", "waarde": "4"}]}
    assert csrf_client.post("/api/cellen", json=body).status_code == 400
    assert Dienst.query.count() == 0
    kop = {"X-CSRFToken": token(csrf_client, "/week/2026/10")}
    antwoord = csrf_client.post("/api/cellen", json=body, headers=kop)
    assert antwoord.status_code == 200 and antwoord.json["fouten"] == []
    assert Dienst.query.one().datum == date(2026, 3, 2)


def test_uitloggen_zonder_token_geweigerd(csrf_client):
    inloggen(csrf_client)
    assert csrf_client.post("/uitloggen").status_code == 400
    assert csrf_client.get("/beheer/").status_code == 200
    assert csrf_client.post("/uitloggen", data={"csrf_token": token(csrf_client, "/kalender/")}
                            ).status_code == 302
