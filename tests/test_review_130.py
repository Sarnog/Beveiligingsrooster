"""Bevindingen uit de code-review van 1.3.0 (elk eerst als falende test)."""

import logging

import pytest

from app.extensions import db
from app.models import ApiToken, Gebruiker, Logboek, LoginPoging
from app.services import api_tokens, klok

from .conftest import WACHTWOORD, login


def _token(gebruikersnaam="collega"):
    token, _ = api_tokens.maak(Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).one(), "x", 30)
    db.session.commit()
    return token


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# 1. Foute API-tokens mogen het inloggen op de website niet blokkeren
def test_foute_tokens_blokkeren_website_login_niet(app, klaar):
    client = app.test_client()
    for _ in range(25):
        client.get("/api/v1/ik", headers=_bearer("br_fout" + "x" * 30))
    login(client, "collega", "tikfout")  # één tikfout van een collega op hetzelfde adres
    assert login(client, "collega").status_code == 302  # juist wachtwoord: gewoon binnen


# 2. Een geldig token werkt ook als hetzelfde adres veel foute tokens stuurde
def test_geldig_token_werkt_ondanks_blokkade_van_foute(app, klaar):
    goed = _token()
    client = app.test_client()
    for _ in range(25):
        client.get("/api/v1/ik", headers=_bearer("br_fout" + "x" * 30))
    assert client.get("/api/v1/ik", headers=_bearer("br_fout" + "x" * 30)).status_code == 429
    assert client.get("/api/v1/ik", headers=_bearer(goed)).status_code == 200
    assert Logboek.query.filter_by(actie="API geblokkeerd").count() == 1


def test_verlopen_token_telt_niet_als_inbraakpoging(app, klaar, monkeypatch):
    from datetime import timedelta

    token = _token()
    later = klok.utc_nu() + timedelta(days=31)
    monkeypatch.setattr(klok, "utc_nu", lambda: later)
    client = app.test_client()
    for _ in range(25):  # een app met een verlopen token blijft het proberen
        assert client.get("/api/v1/ik", headers=_bearer(token)).status_code == 401
    assert LoginPoging.query.filter_by(gebruikersnaam=api_tokens.POGING_NAAM).count() == 0


# 3. Een gedeactiveerd account: even lange rekentijd (wachtwoord wordt toch gecontroleerd)
def test_gedeactiveerd_account_controleert_wel_het_wachtwoord(app, client, klaar, monkeypatch):
    from app.blueprints import auth

    aanroepen = []
    monkeypatch.setattr(auth, "controleer_wachtwoord", lambda h, w: aanroepen.append(w) or True)
    gebruiker = Gebruiker.query.filter_by(gebruikersnaam="collega").one()
    gebruiker.actief = False
    db.session.commit()
    assert login(client, "collega").status_code != 302
    assert aanroepen == [WACHTWOORD]


# 4. Fout bij het plannen van de agenda ná een geslaagde import: import blijft staan
def test_import_geslaagd_ook_als_agenda_plannen_faalt(app, klaar, tmp_path, monkeypatch):
    from app.models import Medewerker
    from app.services import excel_import, sync_planning

    from .test_import_backup import maak_testbestand

    pad = str(tmp_path / "rooster.xlsm")
    maak_testbestand(pad)

    def kapot(medewerker):
        raise RuntimeError("database even op slot")

    monkeypatch.setattr(sync_planning, "plan_volledig", kapot)
    resultaat = excel_import.importeer(excel_import.lees_bestand(pad))
    assert resultaat["diensten"] > 0 and Medewerker.query.count() > 0


# 5. Een logaanroep met verkeerde argumenten mag de app niet laten vastlopen
def test_maskeerfilter_breekt_niet_bij_verkeerde_argumenten():
    from app.debuglog import MaskeerTokens

    record = logging.LogRecord("x", logging.DEBUG, __file__, 1, "%s %s", ("een",), None)
    assert MaskeerTokens().filter(record) is True


# 10. Back-uplabel: alleen kleine letters, cijfers en '-', anders wordt hij nooit opgeruimd
@pytest.mark.parametrize("label", ["Voor_Update", "met spatie", "../weg"])
def test_backup_label_wordt_gecontroleerd(app, klaar, label):
    resultaat = app.test_cli_runner().invoke(args=["backup", "--label", label])
    assert resultaat.exit_code != 0 and "label" in resultaat.output.lower()


def test_api_tokens_tabel_bestaat(app):
    assert ApiToken.query.count() == 0
