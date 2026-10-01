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


# ---------- Twee diensten op één dag (1.4.0): uren per dienst ----------

def test_uren_per_dienst_bij_twee_diensten(app, klaar):
    from datetime import date

    from app.extensions import db
    from app.models import Dienst, Feestdag, Medewerker
    from app.services import instellingen
    from app.services.rooster import herbereken_alle
    from app.services.voorbeeldpakket import laad_voorbeeldpakket
    from app.services.weekrooster import Wijziging, week_gegevens, weektotaal, wijzig_cellen

    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.commit()
    maandag, zaterdag = date(2026, 3, 2), date(2026, 3, 7)
    # BHV 08:30-12:30 (4 uur, geen pauze) en VW Avond 14:30-23:00 (8,5 - 0,5 pauze = 8)
    wijzig_cellen([Wijziging(medewerker.id, maandag, "code", "17/3"),
                   Wijziging(medewerker.id, zaterdag, "code", "17/3")])

    def uren_op(dag):
        db.session.expire_all()
        return {d.volgnummer: d.uren_berekend for d in Dienst.query.filter_by(datum=dag)}

    assert uren_op(maandag) == {1: 4.0, 2: 8.0}  # pauze-aftrek per dienst, niet over de dag
    assert uren_op(zaterdag) == {1: 6.0, 2: 12.0}  # zaterdagtoeslag 1,5 op elke dienst
    assert weektotaal(medewerker.id, maandag) == 30.0
    assert week_gegevens(2026, 10)["rijen"][0].weektotaal == 30.0

    # Feestdag met eigen toeslag: herberekenen werkt per dienst
    instellingen.schrijf("toeslag_feestdag", "2.0")
    db.session.add(Feestdag(jaar=2026, datum=maandag, naam="Eigen dag"))
    db.session.commit()
    herbereken_alle()
    assert uren_op(maandag) == {1: 8.0, 2: 16.0}
