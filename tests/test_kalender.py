"""Kalenderlogica: ISO-weken, week 53, Pasen, feestdagen, werkdagen, tijden."""

from datetime import date

import pytest

from app.services.kalender import (
    aantal_weken,
    dagen_van_week,
    koningsdag,
    maand_raster,
    maandag_van_week,
    nederlandse_feestdagen,
    pasen,
    week_van,
    werkdagen,
)
from app.services.medewerkers import voorstel_initialen
from app.services.tijden import OngeldigeTijd, normaliseer_tijd, parse_datum


def test_pasen():
    assert pasen(2026) == date(2026, 4, 5)
    assert pasen(2025) == date(2025, 4, 20)
    assert pasen(2024) == date(2024, 3, 31)
    assert pasen(2019) == date(2019, 4, 21)


def test_koningsdag_op_zondag_wordt_zaterdag():
    assert koningsdag(2026) == date(2026, 4, 27)
    assert koningsdag(2025) == date(2025, 4, 26)
    assert koningsdag(2031) == date(2031, 4, 26)


def test_feestdagen_2026():
    dagen = {sleutel: datum for sleutel, _naam, datum in nederlandse_feestdagen(2026)}
    assert dagen["goede_vrijdag"] == date(2026, 4, 3)
    assert dagen["tweede_paasdag"] == date(2026, 4, 6)
    assert dagen["hemelvaartsdag"] == date(2026, 5, 14)
    assert dagen["eerste_pinksterdag"] == date(2026, 5, 24)
    assert dagen["tweede_pinksterdag"] == date(2026, 5, 25)
    namen = [naam for _s, naam, _d in nederlandse_feestdagen(2026)]
    assert "Hemelvaartsdag" in namen and len(namen) == 11


def test_iso_week_1_begint_in_december():
    assert maandag_van_week(2026, 1) == date(2025, 12, 29)
    assert week_van(date(2025, 12, 29)) == (2026, 1)
    assert dagen_van_week(2026, 1)[-1] == date(2026, 1, 4)


@pytest.mark.parametrize("jaar, weken", [(2026, 53), (2020, 53), (2015, 53), (2027, 52), (2025, 52)])
def test_aantal_weken(jaar, weken):
    assert aantal_weken(jaar) == weken


def test_werkdagen_zoals_networkdays():
    # Meivakantie 2026: ma 27-04 t/m zo 03-05 = 5 werkdagen
    assert werkdagen(date(2026, 4, 27), date(2026, 5, 3)) == 5
    # Kerstvakantie over de jaargrens
    assert werkdagen(date(2026, 12, 19), date(2027, 1, 3)) == 10
    assert werkdagen(date(2026, 5, 2), date(2026, 5, 3)) == 0


def test_maand_raster():
    weken = maand_raster(2026, 2)
    assert weken[0][6] == date(2026, 2, 1)  # 1 februari 2026 is een zondag
    assert all(len(w) == 7 for w in weken)


@pytest.mark.parametrize(
    "invoer, verwacht",
    [("715", "07:15"), ("7:15", "07:15"), ("07.15", "07:15"), ("0715", "07:15"),
     ("7", "07:00"), ("2330", "23:30"), ("24:00", "00:00"), ("", None), (None, None)],
)
def test_tijd_normaliseren(invoer, verwacht):
    assert normaliseer_tijd(invoer) == verwacht


@pytest.mark.parametrize("invoer", ["2575", "7:60", "abc", "12345", "7:15:00"])
def test_ongeldige_tijd(invoer):
    with pytest.raises(OngeldigeTijd):
        normaliseer_tijd(invoer)


def test_datum_lezen():
    assert parse_datum("05-04-2026") == date(2026, 4, 5)
    assert parse_datum("5-4", standaard_jaar=2026) == date(2026, 4, 5)
    assert parse_datum("2026-04-05") == date(2026, 4, 5)
    assert parse_datum("31-02-2026") is None
    assert parse_datum("onzin") is None


def test_initialen_zoals_excel():
    assert voorstel_initialen("Jan Jansen") == "JJA"
    assert voorstel_initialen("M. Voorbeeld") == "MVO"
    assert voorstel_initialen("Medewerker") == "M"
    assert voorstel_initialen("") == ""
