"""API voor een latere app: /api/v1 (alleen lezen) met persoonlijke API-tokens."""

import re
from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import ApiToken, Dienst, Dienstcode, Gebruiker, Logboek, Medewerker
from app.services import instellingen, klok
from app.services.voorbeeldpakket import laad_voorbeeldpakket

from .conftest import WACHTWOORD, login

VANDAAG = date(2026, 3, 4)  # woensdag, week 10
TOKEN_IN_PAGINA = re.compile(r'data-nieuw-token>(br_[A-Za-z0-9_-]+)<')


@pytest.fixture
def rooster(klaar, monkeypatch):
    monkeypatch.setattr(klok, "vandaag", lambda: VANDAAG)
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA", volgorde=1)
    andere = Medewerker(naam="Medewerker B", initialen="TSB", volgorde=2)
    db.session.add_all([medewerker, andere])
    db.session.commit()
    code = Dienstcode.query.filter_by(nummer=4).one()
    for dagen in (0, 2, 70):
        db.session.add(Dienst(medewerker_id=medewerker.id, datum=VANDAAG + timedelta(days=dagen),
                              dienstcode_id=code.id, begin="07:15", eind="15:45", uren_berekend=8.0,
                              opmerking_tekst="Locatie A" if dagen == 0 else ""))
    db.session.add(Dienst(medewerker_id=andere.id, datum=VANDAAG, dienstcode_id=code.id,
                          begin="07:15", eind="15:45", uren_berekend=8.0))
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.medewerker_id = medewerker.id
    db.session.commit()
    return {"mw": medewerker, "andere": andere}


def maak_token(client, gebruikersnaam="collega", naam="Telefoon", dagen="90") -> str:
    login(client, gebruikersnaam)
    antwoord = client.post("/account/tokens", data={"naam": naam, "dagen": dagen})
    assert antwoord.status_code == 200
    gevonden = TOKEN_IN_PAGINA.search(antwoord.get_data(as_text=True))
    assert gevonden, "token wordt niet getoond na het aanmaken"
    return gevonden.group(1)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tokens aanmaken, tonen en intrekken (Account → API-tokens)
# ---------------------------------------------------------------------------

def test_token_aanmaken_eenmalig_getoond_en_als_hash_bewaard(app, rooster):
    client = app.test_client()
    token = maak_token(client)
    opgeslagen = ApiToken.query.one()
    assert token not in (opgeslagen.token_hash, opgeslagen.prefix)
    assert len(opgeslagen.token_hash) == 64 and token.startswith(opgeslagen.prefix)
    assert opgeslagen.naam == "Telefoon"
    assert opgeslagen.verloopt_op.date() == (klok.utc_nu() + timedelta(days=90)).date()
    # Daarna nooit meer te zien
    pagina = client.get("/account/tokens").get_data(as_text=True)
    assert token not in pagina and "Telefoon" in pagina and opgeslagen.prefix in pagina
    regel = Logboek.query.filter_by(actie="API-token aangemaakt").one()
    assert regel.gebruiker == "collega" and "Telefoon" in regel.details and token not in regel.details


def test_token_geldigheid_beperkt(app, rooster):
    client = app.test_client()
    login(client, "collega")
    assert client.post("/account/tokens", data={"naam": "x", "dagen": "9999"}).status_code == 400
    assert client.post("/account/tokens", data={"naam": "", "dagen": "30"}).status_code == 400
    assert ApiToken.query.count() == 0


def test_token_intrekken(app, rooster):
    client = app.test_client()
    token = maak_token(client)
    assert client.get("/api/v1/ik", headers=bearer(token)).status_code == 200
    token_id = ApiToken.query.one().id
    antwoord = client.post(f"/account/tokens/{token_id}/intrekken")
    assert antwoord.status_code == 302
    assert ApiToken.query.count() == 0
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401
    assert Logboek.query.filter_by(actie="API-token ingetrokken").count() == 1


def test_token_van_een_ander_intrekken_kan_niet(app, rooster):
    maak_token(app.test_client(), "collega")
    token_id = ApiToken.query.one().id
    beheerder = app.test_client()
    login(beheerder, "beheerder")
    assert beheerder.post(f"/account/tokens/{token_id}/intrekken").status_code == 404
    assert ApiToken.query.count() == 1


def test_account_tokens_met_csrf(app, rooster):
    """Formulieren met een sessie: CSRF blijft verplicht."""
    from .test_csrf import inloggen, token

    app.config["WTF_CSRF_ENABLED"] = True
    client = app.test_client()
    inloggen(client)
    assert client.post("/account/tokens", data={"naam": "x", "dagen": "30"}).status_code == 400
    antwoord = client.post("/account/tokens", data={"naam": "x", "dagen": "30",
                                                    "csrf_token": token(client, "/account/tokens")})
    assert antwoord.status_code == 200 and ApiToken.query.count() == 1


# ---------------------------------------------------------------------------
# Inloggen met een token
# ---------------------------------------------------------------------------

def test_api_zonder_inloggen_geeft_json_401(client, rooster):
    antwoord = client.get("/api/v1/ik")
    assert antwoord.status_code == 401 and antwoord.is_json and "fout" in antwoord.json
    assert client.get("/api/v1/ik", headers=bearer("br_onzin")).status_code == 401
    assert client.get("/api/v1/ik", headers={"Authorization": "Basic abc"}).status_code == 401


def test_api_met_sessie_werkt_ook(app, rooster):
    client = app.test_client()
    login(client, "collega")
    assert client.get("/api/v1/ik").json["gebruiker"]["gebruikersnaam"] == "collega"


def test_token_werkt_alleen_voor_de_api(app, rooster):
    token = maak_token(app.test_client())
    client = app.test_client()
    antwoord = client.get("/kalender/", headers=bearer(token))
    assert antwoord.status_code == 302 and "/login" in antwoord.headers["Location"]


def test_token_zet_geen_sessiecookie(app, rooster):
    token = maak_token(app.test_client())
    antwoord = app.test_client().get("/api/v1/ik", headers=bearer(token))
    assert antwoord.status_code == 200
    assert not any(c.startswith("session=") for c in antwoord.headers.getlist("Set-Cookie"))


def test_verlopen_token(app, rooster, monkeypatch):
    token = maak_token(app.test_client(), dagen="30")
    later = klok.utc_nu() + timedelta(days=31)
    monkeypatch.setattr(klok, "utc_nu", lambda: later)
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401


def test_token_ongeldig_na_wachtwoord_wijzigen(app, rooster):
    client = app.test_client()
    token = maak_token(client)
    client.post("/account/wachtwoord", data={"huidig": WACHTWOORD, "nieuw": "nieuwwachtwoord1",
                                              "herhaling": "nieuwwachtwoord1"})
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401


def test_token_ongeldig_na_reset_en_deactiveren(app, rooster):
    token = maak_token(app.test_client())
    gebruiker = Gebruiker.query.filter_by(gebruikersnaam="collega").one()
    gebruiker.maak_sessies_ongeldig()  # zoals bij resetten (beheer of command line)
    db.session.commit()
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401

    token = maak_token(app.test_client())
    gebruiker.actief = False
    db.session.commit()
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401


def test_token_ongeldig_na_terugzetten_backup(app, rooster):
    token = maak_token(app.test_client())
    instellingen.schrijf("sessie_generatie", "nieuw")  # zoals backup.zet_terug
    db.session.commit()
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401


def test_token_laatst_gebruikt(app, rooster):
    token = maak_token(app.test_client())
    assert ApiToken.query.one().laatst_gebruikt is None
    app.test_client().get("/api/v1/ik", headers=bearer(token))
    db.session.expire_all()
    assert isinstance(ApiToken.query.one().laatst_gebruikt, datetime)


def test_rate_limit_op_foute_tokens(app, rooster):
    token = maak_token(app.test_client())
    client = app.test_client()
    for _ in range(20):
        assert client.get("/api/v1/ik", headers=bearer("br_fout" + "x" * 30)).status_code == 401
    # Nu worden onbekende tokens vanaf dit IP geweigerd (429); een geldig token werkt nog
    fout = bearer("br_fout" + "y" * 30)
    antwoord = client.get("/api/v1/ik", headers=fout)
    assert antwoord.status_code == 429 and antwoord.is_json
    assert Logboek.query.filter_by(actie="API geblokkeerd").count() == 1
    client.get("/api/v1/ik", headers=fout)
    assert Logboek.query.filter_by(actie="API geblokkeerd").count() == 1  # één keer loggen
    assert client.get("/api/v1/ik", headers=bearer(token)).status_code == 200


def test_schrijven_met_token_zonder_csrf_en_met_sessie_wel_csrf(app, rooster):
    """Schrijven valt buiten deze versie (405), maar CSRF geldt alleen voor sessies."""
    from app.services import api_tokens

    from .test_csrf import inloggen

    app.config["WTF_CSRF_ENABLED"] = True
    token, _record = api_tokens.maak(Gebruiker.query.filter_by(gebruikersnaam="beheerder").one(), "x", 30)
    db.session.commit()
    assert app.test_client().post("/api/v1/ik", headers=bearer(token)).status_code == 405
    client = app.test_client()
    inloggen(client)
    assert client.post("/api/v1/ik").status_code == 400  # sessie zonder CSRF-token


# ---------------------------------------------------------------------------
# De gegevens
# ---------------------------------------------------------------------------

def test_ik(app, rooster):
    token = maak_token(app.test_client())
    data = app.test_client().get("/api/v1/ik", headers=bearer(token)).json
    assert data["api_versie"] == 1 and data["app_versie"]
    assert data["gebruiker"] == {"id": data["gebruiker"]["id"], "gebruikersnaam": "collega",
                                 "weergavenaam": "Collega", "rol": "gebruiker"}
    assert data["medewerker"] == {"id": rooster["mw"].id, "naam": "Medewerker A", "initialen": "TSA"}


def test_mijn_rooster(app, rooster):
    token = maak_token(app.test_client())
    client = app.test_client()
    data = client.get("/api/v1/mijn-rooster", headers=bearer(token)).json
    assert data["van"] == "2026-03-04" and data["tot"] == "2026-04-28"  # standaard 8 weken
    assert [d["datum"] for d in data["diensten"]] == ["2026-03-04", "2026-03-06"]
    eerste = data["diensten"][0]
    assert eerste == {"datum": "2026-03-04", "volgnummer": 1, "code": 4, "dienstnaam": "VW Vroeg",
                      "begin": "07:15", "eind": "15:45", "uren": 8.0, "opmerking": "Locatie A",
                      "opmerking_begin": None, "opmerking_eind": None,
                      "kleur_achtergrond": "#FF0000", "kleur_tekst": "#FFFFFF"}
    data = client.get("/api/v1/mijn-rooster?van=2026-05-01&tot=2026-05-31", headers=bearer(token)).json
    assert [d["datum"] for d in data["diensten"]] == ["2026-05-13"]


@pytest.mark.parametrize("vraag", ["van=gisteren", "van=2026-05-01&tot=2026-04-01",
                                   "van=2026-01-01&tot=2027-06-01"])
def test_mijn_rooster_ongeldige_periode(app, rooster, vraag):
    token = maak_token(app.test_client())
    antwoord = app.test_client().get(f"/api/v1/mijn-rooster?{vraag}", headers=bearer(token))
    assert antwoord.status_code == 400 and "fout" in antwoord.json


def test_mijn_rooster_zonder_medewerker(app, rooster):
    token = maak_token(app.test_client(), "beheerder")
    antwoord = app.test_client().get("/api/v1/mijn-rooster", headers=bearer(token))
    assert antwoord.status_code == 404 and "medewerker" in antwoord.json["fout"]


def test_week(app, rooster):
    token = maak_token(app.test_client())
    data = app.test_client().get("/api/v1/week/2026/10", headers=bearer(token)).json
    assert data["jaar"] == 2026 and data["week"] == 10
    assert [d["datum"] for d in data["dagen"]][0] == "2026-03-02" and len(data["dagen"]) == 7
    namen = [m["naam"] for m in data["medewerkers"]]
    assert namen == ["Medewerker A", "Medewerker B"]  # zelfde rechten als de webpagina: iedereen
    eerste = data["medewerkers"][0]
    assert eerste["weektotaal"] == 16.0 and len(eerste["dagen"]) == 7
    assert eerste["dagen"][2]["code"] == 4 and eerste["dagen"][0] is None
    assert app.test_client().get("/api/v1/week/2026/54", headers=bearer(token)).status_code == 404


def test_dienstcodes(app, rooster):
    token = maak_token(app.test_client())
    data = app.test_client().get("/api/v1/dienstcodes", headers=bearer(token)).json
    codes = {c["nummer"]: c for c in data["dienstcodes"]}
    assert codes[4]["omschrijving"] == "VW Vroeg" and codes[4]["std_begin"] == "07:15"
    assert codes[10]["std_begin"] is None


def test_api_antwoorden_niet_cachen(app, rooster):
    token = maak_token(app.test_client())
    antwoord = app.test_client().get("/api/v1/dienstcodes", headers=bearer(token))
    assert antwoord.headers["Cache-Control"] == "no-store"


def test_tokens_verdwijnen_met_het_account(app, rooster):
    token = maak_token(app.test_client())
    beheerder = app.test_client()
    login(beheerder, "beheerder")
    gid = Gebruiker.query.filter_by(gebruikersnaam="collega").one().id
    assert beheerder.post(f"/beheer/gebruikers/{gid}/verwijder").status_code == 302
    db.session.expire_all()
    assert ApiToken.query.count() == 0
    assert app.test_client().get("/api/v1/ik", headers=bearer(token)).status_code == 401


def test_openapi_beschrijft_alle_eindpunten(app):
    """docs/openapi.yaml wordt met de hand bijgehouden: alle routes moeten erin staan."""
    from pathlib import Path

    tekst = (Path(__file__).parent.parent / "docs" / "openapi.yaml").read_text(encoding="utf-8")
    beschreven = set(re.findall(r"^  (/[^:]+):$", tekst, re.M))
    routes = {re.sub(r"<(?:int:)?(\w+)>", r"{\1}", r.rule.removeprefix("/api/v1"))
              for r in app.url_map.iter_rules() if r.endpoint.startswith("api_v1.")}
    assert beschreven == routes


def test_tweede_dienst_in_de_api(app, rooster):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(rooster["mw"].id, VANDAAG, "code", "4/3")])
    token = maak_token(app.test_client())
    client = app.test_client()
    data = client.get("/api/v1/mijn-rooster", headers=bearer(token)).json
    vandaag = [(d["volgnummer"], d["dienstnaam"]) for d in data["diensten"]
               if d["datum"] == VANDAAG.isoformat()]
    assert vandaag == [(1, "VW Vroeg"), (2, "VW Avond")]
    jaar, week, dag = VANDAAG.isocalendar()
    data = client.get(f"/api/v1/week/{jaar}/{week}", headers=bearer(token)).json
    eerste = data["medewerkers"][0]
    assert eerste["dagen"][dag - 1]["volgnummer"] == 1
    assert eerste["tweede_diensten"][dag - 1]["dienstnaam"] == "VW Avond"
    assert eerste["tweede_diensten"][dag - 1]["volgnummer"] == 2
    assert [d for i, d in enumerate(eerste["tweede_diensten"]) if i != dag - 1] == [None] * 6
    # 8 (andere dag) + 8,5 + 8,5 - 0,5: de pauze geldt per dag (sinds 1.8.3)
    assert eerste["weektotaal"] == 24.5
