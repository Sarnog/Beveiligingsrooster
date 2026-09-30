"""Urenberekening: alle gevallen uit het oude Excel-bestand (§4.2)."""

import pytest

from app.services.urenberekening import bereken_uren, dagfactor, formatteer_uren

MA, ZA, ZO = 0, 5, 6


def uren(begin, eind, weekdag=MA, **kwargs):
    return bereken_uren(begin, eind, dagfactor(weekdag, **kwargs))


@pytest.mark.parametrize(
    "weekdag, begin, eind, verwacht",
    [
        (MA, "14:30", "23:00", 8.00),
        (MA, "07:15", "16:45", 9.00),
        (MA, "11:00", "23:00", 11.50),
        (MA, "07:15", "13:30", 5.75),
        (MA, "07:15", "16:00", 8.25),
        (MA, "08:30", "12:30", 4.00),  # geen pauze-aftrek
        (MA, "13:30", "15:45", 2.25),
        (ZA, "07:15", "15:45", 12.00),
        (ZO, "07:15", "15:45", 16.00),
        (MA, "22:00", "06:30", 8.00),  # over middernacht
    ],
)
def test_gevallen_uit_excel(weekdag, begin, eind, verwacht):
    assert uren(begin, eind, weekdag) == verwacht


def test_geen_tijden_geeft_geen_uren():
    # Bijvoorbeeld 'Bapo': alleen een dienstnaam
    assert uren(None, None) is None
    assert formatteer_uren(uren(None, None)) == ""


def test_alleen_begintijd_geeft_geen_uren():
    # Excel rekende hier 16,25 uur (07:15 -> 00:00); wij bewust niet
    assert uren("07:15", None) is None


def test_precies_vijf_en_half_uur_geen_pauze():
    assert uren("08:00", "13:30") == 5.5
    assert uren("08:00", "13:31") == 5.0  # 5,52 - 0,5 = 5,02 -> afgerond 5,00


def test_bankiersafronding_zoals_vba():
    # Python's round() rondt 'half naar even' af, net als VBA's Round()
    assert round(6.5) == 6 and round(7.5) == 8
    # Zaterdag 00:00-01:15: 1,25 x 1,5 x 4 = 7,5 (exact) -> half naar even = 8 -> 2,00
    assert uren("00:00", "01:15", ZA) == 2.0


def test_kommagetal_afwijkingen_zoals_vba():
    # Zelfde rekenstappen als de VBA (fracties van een dag). Daardoor komt
    # 10:00-11:15 uit op 7,4999... x -> 7 -> 1,75 en 12:00-13:15 op 7,5000...1 -> 2,00.
    # Precies wat Excel ook zou berekenen.
    assert uren("10:00", "11:15", ZA) == 1.75
    assert uren("12:00", "13:15", ZA) == 2.0


def test_eigen_toeslagfactoren():
    assert uren("07:15", "15:45", ZA, factor_zaterdag=1.25) == 10.0
    assert uren("07:15", "15:45", ZO, factor_zondag=1.5) == 12.0


def test_feestdag_standaard_zonder_toeslag():
    assert uren("07:15", "15:45", MA, is_feestdag=True) == 8.0


def test_feestdag_met_toeslag_hoogste_factor_telt():
    assert uren("07:15", "15:45", MA, is_feestdag=True, factor_feestdag=1.5) == 12.0
    # Feestdag op zondag: max(2,0; 1,5) = 2,0 (niet vermenigvuldigen)
    assert uren("07:15", "15:45", ZO, is_feestdag=True, factor_feestdag=1.5) == 16.0


def test_formatteren():
    assert formatteer_uren(8.25) == "8,25"
    assert formatteer_uren(0) == "0,00"
