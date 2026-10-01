"""Rooster exporteren naar MS Excel (.xlsx) en weer importeren (B1, versie 1.5.0)."""

import io
from datetime import date, timedelta

import openpyxl
import pytest

from app.extensions import db
from app.models import Contracturen, Dienst, Dienstcode, Logboek, Medewerker, Vakantie
from app.services import instellingen
from app.services.voorbeeldpakket import laad_voorbeeldpakket
from app.services.weekrooster import Wijziging, wijzig_cellen

MAANDAG = date(2026, 3, 2)  # week 10


@pytest.fixture
def rooster(klaar):
    laad_voorbeeldpakket()
    a = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1)
    b = Medewerker(naam="=HYPERLINK(\"http://x\")", initialen="MB", volgorde=2)  # formule-injectie
    db.session.add_all([a, b])
    db.session.flush()
    db.session.add(Contracturen(medewerker_id=a.id, jaar=2026, uren=1659))
    db.session.add(Vakantie(naam="Voorjaarsvakantie", datum_van=date(2026, 2, 16),
                            datum_tot=date(2026, 2, 22)))
    db.session.commit()
    dinsdag, woensdag, donderdag = (MAANDAG + timedelta(days=i) for i in (1, 2, 3))
    _, fouten = wijzig_cellen([
        Wijziging(a.id, MAANDAG, "code", "4"), Wijziging(a.id, MAANDAG, "opmerking", "Locatie A"),
        Wijziging(a.id, MAANDAG, "opm_begin", "13:30"), Wijziging(a.id, MAANDAG, "opm_eind", "15:45"),
        Wijziging(a.id, dinsdag, "code", "17/3"),  # twee diensten
        Wijziging(a.id, dinsdag, "eind", "22:30", volgnummer=2),  # eigen tijd bij dienst 2
        Wijziging(a.id, woensdag, "dienstnaam", "=SOM(A1:A9)"),  # vrije dienst die op een formule lijkt
        Wijziging(a.id, woensdag, "uren", "6"),
        Wijziging(a.id, donderdag, "code", "4"),
        Wijziging(a.id, donderdag, "dienstnaam", "VW Vroeg tot 12:00"),
        Wijziging(a.id, donderdag, "eind", "12:00"),
        Wijziging(b.id, MAANDAG, "code", "/3"),  # alleen een tweede dienst
        Wijziging(b.id, date(2026, 12, 30), "code", "5"),  # week 53
    ])
    assert fouten == []
    from app.services.weekrooster import pas_dagopmerking_toe

    pas_dagopmerking_toe(MAANDAG, "Eigen dagtekst")
    db.session.commit()
    return {"a": a.id, "b": b.id}


def _download(client, **params):
    antwoord = client.get("/export/rooster.xlsx", query_string=params)
    assert antwoord.status_code == 200, antwoord.data[:300]
    return antwoord, openpyxl.load_workbook(io.BytesIO(antwoord.data))


def test_b1_download_met_bladen_en_bestandsnaam(app, als_beheerder, rooster):
    antwoord, boek = _download(als_beheerder, jaar=2026)
    assert antwoord.headers["Content-Disposition"] == "attachment; filename=rooster-2026.xlsx"
    assert antwoord.mimetype.endswith("spreadsheetml.sheet")
    assert [f"W{w}" for w in range(1, 54)] == [n for n in boek.sheetnames if n.startswith("W")]
    assert {"Lijsten", "Urenoverzicht", "Vakanties", "Kalender"} <= set(boek.sheetnames)
    assert boek["Kalender"]["E2"].value == 2026
    assert boek["Vakanties"]["A2"].value == "Voorjaarsvakantie"
    lijsten = boek["Lijsten"]
    assert (lijsten["B2"].value, lijsten["C2"].value, lijsten["D2"].value) == ("MA", "Medewerker A", 1659)
    regel = Logboek.query.filter_by(actie="Rooster geëxporteerd").one()
    assert "29-12-2025 t/m 03-01-2027" in regel.details


def test_b1_weekblad_lijkt_op_het_weekrooster(app, als_beheerder, rooster):
    _, boek = _download(als_beheerder, jaar=2026)
    blad = boek["W10"]
    assert blad["B4"].value == "Medewerker A" and blad["D3"].value == "Eigen dagtekst"
    assert blad["D4"].value == "Locatie A" and str(blad["D5"].value) == "13:30:00"
    assert blad["D6"].value == "VW Vroeg" and str(blad["E7"].value) == "15:45:00" and blad["F7"].value == 8
    # Kleur van de dienstcode
    code4 = Dienstcode.query.filter_by(nummer=4).one()
    assert blad["D6"].fill.fgColor.rgb.endswith(code4.kleur_achtergrond.lstrip("#").upper())
    # Twee diensten: code-raster '17/3', dienst 2 rechts (vanaf AK) met eigen eindtijd
    assert blad["AD6"].value == "17/3"
    assert blad["AN6"].value == "VW Avond" and str(blad["AO7"].value) == "22:30:00"
    assert blad["Z4"].value == 1659 and blad["Z6"].value > 0  # contracturen en weektotaal
    assert blad["AB6"].value == "MA" and blad["AC6"].value == 4


def test_b1_formule_injectie_wordt_tekst(app, als_beheerder, rooster):
    _, boek = _download(als_beheerder, jaar=2026)
    blad = boek["W10"]
    for cel in (blad["B8"], blad["J6"], boek["Lijsten"]["C3"]):
        assert cel.data_type == "s" and str(cel.value).startswith("=")
    ruw = openpyxl.load_workbook(io.BytesIO(_download(als_beheerder, jaar=2026)[0].data), data_only=False)
    assert ruw["W10"]["B8"].value == '=HYPERLINK("http://x")' and ruw["W10"]["B8"].data_type == "s"


def test_b1_periode_en_een_medewerker(app, als_gebruiker, rooster):
    antwoord, boek = _download(als_gebruiker, van="2026-03-02", tot="2026-03-08", medewerker=rooster["a"])
    naam = "rooster-20260302-20260308-ma.xlsx"
    assert antwoord.headers["Content-Disposition"] == f"attachment; filename={naam}"
    assert [n for n in boek.sheetnames if n.startswith("W")] == ["W10"]
    assert boek["W10"]["B4"].value == "Medewerker A" and boek["W10"]["B8"].value is None
    assert [r[0].value for r in boek["Urenoverzicht"].iter_rows(min_row=2)] == ["Medewerker A"]


def test_b1_ongeldige_keuzes(app, als_gebruiker, rooster):
    for params in ({"van": "2026-12-28", "tot": "2027-01-10"}, {"van": "2026-03-08", "tot": "2026-03-02"},
                   {"jaar": "1800"}, {"van": "onzin", "tot": "2026-03-02"},
                   {"jaar": "2026", "medewerker": "999"}):
        antwoord = als_gebruiker.get("/export/rooster.xlsx", query_string=params)
        assert antwoord.status_code == 302 and "/export/" in antwoord.headers["Location"], params


def test_b1_toegang(app, client, rooster):
    assert client.get("/export/rooster.xlsx?jaar=2026").status_code == 302  # niet ingelogd: naar login
    instellingen.schrijf("deellink_actief", "1")
    instellingen.schrijf("deellink_token", "geheim-token-voor-de-test")
    db.session.commit()
    token = "geheim-token-voor-de-test"
    for pagina in (f"/deel/{token}/week/2026/10", f"/deel/{token}/?jaar=2026"):
        assert "Exporteren (Excel)" not in client.get(pagina).data.decode()


def test_b1_knoppen(app, als_gebruiker, rooster):
    for pagina in ("/week/2026/10", "/kalender/?jaar=2026", "/overzicht/uren?jaar=2026"):
        assert "Exporteren (Excel)" in als_gebruiker.get(pagina).data.decode(), pagina
    assert als_gebruiker.get("/export/?jaar=2026").status_code == 200


def _rooster_als_tuples():
    """Alles wat bij een herimport terug moet komen (op naam, zonder database-ID's)."""
    db.session.expire_all()
    diensten = sorted(
        (d.medewerker.naam, d.datum, d.volgnummer, d.dienstcode.nummer if d.dienstcode else None,
         d.dienstnaam, d.begin, d.eind, d.opmerking_tekst, d.opmerking_begin, d.opmerking_eind,
         d.uren_handmatig, d.uren_berekend)
        for d in Dienst.query.all() if not d.is_leeg or d.volgnummer == 1)
    codes = sorted((c.nummer, c.omschrijving, c.std_begin, c.std_eind) for c in Dienstcode.query.all())
    contract = sorted((c.medewerker.naam, c.jaar, c.uren) for c in Contracturen.query.all())
    return diensten, codes, contract


def test_b1_export_en_weer_importeren_in_een_lege_database(app, als_beheerder, rooster, tmp_path):
    from app import create_app
    from app.services.excel_import import importeer, lees_bestand

    from .conftest import TestConfig

    voor = _rooster_als_tuples()
    assert len(voor[0]) == 8 and any(d[2] == 2 and d[6] == "22:30" for d in voor[0])  # o.a. dienst 2
    assert ("Medewerker A", date(2026, 3, 5), 1, 4, "VW Vroeg tot 12:00") in [d[:5] for d in voor[0]]
    pad = tmp_path / "rooster-2026.xlsx"
    pad.write_bytes(als_beheerder.get("/export/rooster.xlsx?jaar=2026").data)

    leeg = create_app(TestConfig(str(tmp_path / "leeg")))
    with leeg.app_context():
        db.create_all()
        plan = lees_bestand(str(pad), 2026)
        assert plan.waarschuwingen == [] and plan.weektotaal_verschillen() == []
        importeer(plan)
        na = _rooster_als_tuples()
        db.session.remove()
    assert na[0] == voor[0]  # diensten, tijden, opmerkingen, uren, twee diensten
    assert na[1] == voor[1]  # dienstcodes
    assert na[2] == voor[2]  # contracturen
