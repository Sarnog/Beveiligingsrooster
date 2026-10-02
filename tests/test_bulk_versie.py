"""Bulkacties (import, uitrollen, herhalen) met optimistic locking, zoals het weekrooster.

Wijzigt een planner tegelijk een dienst tussen het voorbeeld (effect) en het toepassen, dan wordt
alles teruggedraaid en verschijnt een duidelijke melding. Alle testdata is fictief.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.extensions import db
from app.models import Dienst, Logboek
from app.services import excel_import, patronen
from app.services.excel_import import lees_bestand
from app.services.weekrooster import VersieConflict, Wijziging, wijzig_cellen

from .test_import_backup import keuzeformulier, upload
from .test_import_keuzes import _bestand_2026, basis  # noqa: F401  (fixture)
from .test_patronen import MAANDAG, _cel, _herhaal, _keuzes, _patroon, _plan_acht_weken, mw  # noqa: F401

GELIJKTIJDIG = "Iemand anders wijzigde tegelijk"


def _tussendoor(monkeypatch, module, naam: str) -> list[bool]:
    """Na de droogloop (effect) verhoogt 'een andere planner' de versie van alle diensten.

    Geeft een schakelaar terug: alleen als die aan staat gebeurt dat (zo blijft het voorbeeld
    in de schermtests ongemoeid).
    """
    origineel = getattr(module, naam)
    aan = [True]

    def met_wijziging(*args, **kwargs):
        uitkomst = origineel(*args, **kwargs)
        if aan[0]:
            db.session.execute(text("UPDATE dienst SET versie = versie + 1"))
        return uitkomst

    monkeypatch.setattr(module, naam, met_wijziging)
    return aan


def test_uitrollen_versieconflict_draait_alles_terug(app, mw, monkeypatch):  # noqa: F811
    a = mw[0]
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "5")])[1] == []
    patroon = _patroon(weken=1, cellen={(1, 0): "4", (1, 1): "4"})
    _tussendoor(monkeypatch, patronen, "effect")
    with pytest.raises(VersieConflict, match=GELIJKTIJDIG):
        patronen.pas_toe(patroon, _keuzes(patroon, [(a.id, 1)], MAANDAG, MAANDAG + timedelta(days=6)))
    assert _cel(a, MAANDAG) == "5" and _cel(a, MAANDAG + timedelta(days=1)) == ""
    assert Logboek.query.filter_by(actie="Roosterpatroon toegepast").count() == 0


def test_herhalen_versieconflict_draait_alles_terug(app, mw, monkeypatch):  # noqa: F811
    a = mw[0]
    _plan_acht_weken([a])
    doel = MAANDAG + timedelta(weeks=8)
    assert wijzig_cellen([Wijziging(a.id, doel + timedelta(days=1), "code", "5")])[1] == []
    _tussendoor(monkeypatch, patronen, "herhaal_effect")
    with pytest.raises(VersieConflict, match=GELIJKTIJDIG):
        patronen.herhaal_pas_toe(_herhaal([a], doel, doel + timedelta(weeks=8, days=-1)))
    assert _cel(a, doel) == "" and _cel(a, doel + timedelta(days=1)) == "5"
    assert Logboek.query.filter_by(actie="Rooster herhaald").count() == 0


def test_import_versieconflict_draait_alles_terug(app, basis, tmp_path, monkeypatch):  # noqa: F811
    _tussendoor(monkeypatch, excel_import, "effect")
    voor = {(d.medewerker_id, d.datum, d.volgnummer): d.dienstnaam_override for d in Dienst.query}
    with pytest.raises(VersieConflict, match=GELIJKTIJDIG):
        excel_import.importeer(lees_bestand(_bestand_2026(tmp_path), 2026))
    db.session.expire_all()
    assert {(d.medewerker_id, d.datum, d.volgnummer): d.dienstnaam_override for d in Dienst.query} == voor


def test_schermen_melden_versieconflict(app, als_beheerder, mw, monkeypatch):  # noqa: F811
    a = mw[0]
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "5")])[1] == []
    # Uitrollen
    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    url = f"/beheer/patronen/{patroon.id}/uitrollen"
    keuzes = {"mw": [a.id], f"start-{a.id}": "1", "van": "2026-W10", "tot_week": "2026-W10",
              "modus": "overschrijven", "feestdagen": "invullen"}
    aan = _tussendoor(monkeypatch, patronen, "effect")
    aan[0] = False
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    aan[0] = True
    tekst = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                               follow_redirects=True).data.decode()
    assert GELIJKTIJDIG in tekst and "er is niets gewijzigd" in tekst and _cel(a, MAANDAG) == "5"
    # Herhalen
    url = "/beheer/patronen/herhalen"
    keuzes = {"mw": [a.id], "bron": "2026-W10", "weken": "1", "van": "2026-W11", "tot_week": "2026-W11",
              "modus": "overschrijven", "feestdagen": "invullen"}
    assert wijzig_cellen([Wijziging(a.id, MAANDAG + timedelta(weeks=1), "code", "7")])[1] == []
    aan = _tussendoor(monkeypatch, patronen, "herhaal_effect")
    aan[0] = False
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    aan[0] = True
    tekst = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                               follow_redirects=True).data.decode()
    assert GELIJKTIJDIG in tekst and _cel(a, MAANDAG + timedelta(weeks=1)) == "7"


def test_importscherm_meldt_versieconflict(app, als_beheerder, basis, tmp_path, monkeypatch):  # noqa: F811
    upload(als_beheerder, _bestand_2026(tmp_path))
    als_beheerder.get("/beheer/importeren/voorbeeld")
    _tussendoor(monkeypatch, excel_import, "effect")
    antwoord = als_beheerder.post("/beheer/importeren/voorbeeld", data=keuzeformulier(),
                                  follow_redirects=True)
    tekst = antwoord.data.decode()
    assert GELIJKTIJDIG in tekst and "er is niets gewijzigd" in tekst
    db.session.expire_all()
    assert Dienst.query.filter_by(datum=date(2026, 3, 2)).first().dienstnaam_override == "Oud"
