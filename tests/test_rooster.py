"""Weekrooster, kalender, overzichten, zoeken, logboek en deellink (fase 2)."""

from datetime import date

import pytest

from app.extensions import db
from app.models import Contracturen, Dagopmerking, Dienst, Gebruiker, Logboek, Medewerker, Vakantie
from app.services import instellingen
from app.services.voorbeeldpakket import laad_voorbeeldpakket

MAANDAG = date(2026, 3, 2)  # week 10 van 2026
ZATERDAG = date(2026, 3, 7)


@pytest.fixture
def rooster(klaar):
    """Voorbeeldpakket + twee fictieve medewerkers."""
    laad_voorbeeldpakket()
    a = Medewerker(naam="Medewerker A", initialen="TSA", volgorde=1)
    b = Medewerker(naam="Medewerker B", initialen="TSB", volgorde=2)
    db.session.add_all([a, b])
    db.session.commit()
    return {"a": a, "b": b}


def cel(client, mw, datum, veld, waarde, versie=None):
    wijziging = {"mw": mw.id, "datum": datum.isoformat(), "veld": veld, "waarde": waarde}
    if versie is not None:
        wijziging["versie"] = versie
    return client.post("/api/cellen", json={"wijzigingen": [wijziging], "opslaan": True})


def dienst(mw, datum):
    db.session.expire_all()
    return Dienst.query.filter_by(medewerker_id=mw.id, datum=datum).first()


def test_code_invoeren_zet_naam_tijden_en_uren(als_beheerder, rooster):
    antwoord = cel(als_beheerder, rooster["a"], MAANDAG, "code", "4")
    assert antwoord.status_code == 200
    gegevens = antwoord.json["bijgewerkt"][f"{rooster['a'].id}|{MAANDAG.isoformat()}"]
    assert gegevens["dienstnaam"] == "VW Vroeg"
    assert (gegevens["begin"], gegevens["eind"], gegevens["uren"]) == ("07:15", "15:45", "8,00")
    assert gegevens["weektotaal"] == "8,00"
    assert "background:#FF0000" in gegevens["dienst_stijl"]
    assert Logboek.query.filter_by(actie="Rooster gewijzigd").count() == 1


def test_zaterdag_krijgt_toeslag(als_beheerder, rooster):
    cel(als_beheerder, rooster["a"], ZATERDAG, "code", "4")
    assert dienst(rooster["a"], ZATERDAG).uren_berekend == 12.0


def test_onbekende_code_geeft_fout_en_wordt_niet_opgeslagen(als_beheerder, rooster):
    antwoord = cel(als_beheerder, rooster["a"], MAANDAG, "code", "99")
    assert antwoord.json["fouten"][0]["melding"] == "Onbekende dienstcode: 99"
    assert dienst(rooster["a"], MAANDAG) is None
    antwoord = cel(als_beheerder, rooster["a"], MAANDAG, "code", "abc")
    assert antwoord.json["fouten"]


def test_blanco_code_en_lege_cel_betekenen_geen_dienst(als_beheerder, rooster):
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "4")
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "15")
    assert dienst(rooster["a"], MAANDAG) is None  # lege regel wordt opgeruimd
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "4")
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "")
    assert dienst(rooster["a"], MAANDAG) is None


def test_handmatige_tijd_en_terug_naar_standaard(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")
    antwoord = cel(als_beheerder, a, MAANDAG, "eind", "1600")  # 16:00 i.p.v. 15:45
    gegevens = antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]
    assert gegevens["eind"] == "16:00" and gegevens["handmatig"] and gegevens["uren"] == "8,25"
    # Code opnieuw invoeren: standaardtijden komen terug
    cel(als_beheerder, a, MAANDAG, "code", "5")
    d = dienst(a, MAANDAG)
    assert (d.begin, d.eind, d.tijden_handmatig, d.uren_berekend) == ("07:15", "16:45", False, 9.0)


def test_ongeldige_tijd(als_beheerder, rooster):
    antwoord = cel(als_beheerder, rooster["a"], MAANDAG, "begin", "25:99")
    assert "Ongeldige tijd" in antwoord.json["fouten"][0]["melding"]


def test_dienst_zonder_tijden_geeft_geen_uren(als_beheerder, rooster):
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "10")  # Bapo
    d = dienst(rooster["a"], MAANDAG)
    assert d.dienstnaam == "Bapo" and d.uren_berekend is None


def test_optimistic_locking(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4", versie=0)
    # Een tweede beheerder met een verouderde versie (0) krijgt een melding
    antwoord = cel(als_beheerder, a, MAANDAG, "code", "5", versie=0)
    assert antwoord.json["fouten"][0]["conflict"] is True
    assert dienst(a, MAANDAG).dienstcode.nummer == 4
    # Met de juiste versie lukt het wel
    cel(als_beheerder, a, MAANDAG, "code", "5", versie=1)
    assert dienst(a, MAANDAG).dienstcode.nummer == 5


def test_plakken_meerdere_cellen_in_een_verzoek(als_beheerder, rooster):
    a, b = rooster["a"], rooster["b"]
    wijzigingen = [
        {"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "4", "versie": 0},
        {"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "opmerking", "waarde": "BHV", "versie": None},
        {"mw": b.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "7", "versie": 0},
    ]
    antwoord = als_beheerder.post("/api/cellen", json={"wijzigingen": wijzigingen, "opslaan": True})
    assert antwoord.json["fouten"] == []
    assert dienst(a, MAANDAG).opmerking_tekst == "BHV"
    assert dienst(b, MAANDAG).dienstnaam == "OB Vroeg"


def test_opmerkingtijden_tellen_standaard_niet_mee(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "opmerking", "BV")
    cel(als_beheerder, a, MAANDAG, "opm_begin", "13:30")
    cel(als_beheerder, a, MAANDAG, "opm_eind", "15:45")
    assert dienst(a, MAANDAG).uren_berekend is None
    instellingen.schrijf("opmerkingtijden_meetellen", "1")
    db.session.commit()
    cel(als_beheerder, a, MAANDAG, "opm_eind", "16:00")
    assert dienst(a, MAANDAG).uren_berekend == 2.5


def test_dagopmerking_automatisch_en_handmatig(als_beheerder, rooster):
    db.session.add(Vakantie(naam="Meivakantie", datum_van=date(2026, 4, 27), datum_tot=date(2026, 5, 3)))
    db.session.commit()
    pagina = als_beheerder.get("/week/2026/18").data.decode()
    assert "Koningsdag" in pagina  # feestdag gaat voor vakantie op 27-04
    assert "Meivakantie" in pagina  # overige werkdagen

    dag = date(2026, 4, 28)

    def dagopmerking(tekst):
        antwoord = als_beheerder.post("/api/cellen", json={
            "opslaan": True, "dagopmerkingen": [{"datum": dag.isoformat(), "tekst": tekst}]})
        return antwoord.json["dagopmerkingen"][dag.isoformat()]

    assert dagopmerking("Extra inzet") == {"tekst": "Extra inzet", "handmatig": True}
    # Wissen: automatische tekst komt terug
    assert dagopmerking("") == {"tekst": "Meivakantie", "handmatig": False}
    # Nogmaals wissen: automatische tekst wordt verborgen
    assert dagopmerking("") == {"tekst": "", "handmatig": True}
    assert Dagopmerking.query.count() == 1


def test_weekpagina_beheerder_ziet_code_raster(als_beheerder, rooster):
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "4")
    pagina = als_beheerder.get("/week/2026/10").data.decode()
    assert 'data-raster="codes"' in pagina and "data-api-cellen" in pagina
    assert "VW Vroeg" in pagina and "Medewerker A" in pagina and "ma 02-03-26" in pagina


def test_weekpagina_gebruiker_ziet_alleen_het_rooster(als_gebruiker, rooster):
    pagina = als_gebruiker.get("/week/2026/10").data.decode()
    assert "Medewerker A" in pagina
    assert 'data-raster="codes"' not in pagina and "data-api-cellen" not in pagina
    assert 'class="cel' not in pagina


def test_week_53_alleen_als_die_bestaat(als_beheerder, rooster):
    assert als_beheerder.get("/week/2026/53").status_code == 200
    assert als_beheerder.get("/week/2027/53").status_code == 404
    antwoord = als_beheerder.get("/week?dag=2025-12-30")
    assert "/week/2026/1" in antwoord.headers["Location"]


def test_gearchiveerde_medewerker_verdwijnt_uit_nieuwe_weken(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")
    a = db.session.get(Medewerker, a.id)
    a.gearchiveerd_vanaf = date(2026, 3, 9)
    db.session.commit()
    assert "Medewerker A" in als_beheerder.get("/week/2026/10").data.decode()  # historie blijft
    assert "Medewerker A" not in als_beheerder.get("/week/2026/11").data.decode()


def test_week_kopieren(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")
    cel(als_beheerder, a, MAANDAG, "eind", "16:00")
    als_beheerder.post("/week/2026/10/kopieer", data={"naar": "2026-W12", "medewerker_id": ""})
    kopie = dienst(a, date(2026, 3, 16))
    assert kopie.dienstnaam == "VW Vroeg" and kopie.eind == "16:00" and kopie.tijden_handmatig
    assert kopie.uren_berekend == 8.25


def test_kalender_en_overzicht(als_beheerder, rooster):
    a = rooster["a"]
    db.session.get(Medewerker, a.id).contracturen.append(Contracturen(jaar=2026, uren=1659))
    db.session.commit()
    cel(als_beheerder, a, MAANDAG, "code", "4")
    cel(als_beheerder, a, ZATERDAG, "code", "4")
    pagina = als_beheerder.get("/kalender/?jaar=2026").data.decode()
    assert "Hemelvaartsdag" in pagina and "Koningsdag" in pagina
    assert "20,00" in pagina  # gewerkt: 8 + 12
    assert "-1639,00" in pagina and "negatief" in pagina
    # Urenoverzicht: week 10 = 20,00
    overzicht = als_beheerder.get("/overzicht/uren?jaar=2026").data.decode()
    assert "20.00" in overzicht and "W53" in overzicht
    csv = als_beheerder.get("/overzicht/uren.csv?jaar=2026").data.decode("utf-8-sig")
    assert "Medewerker A;TSA" in csv


def test_zoek_datum(als_beheerder, rooster):
    antwoord = als_beheerder.get("/kalender/zoek?datum=05-04&jaar=2026")
    assert antwoord.headers["Location"].endswith("/week/2026/14?dag=2026-04-05")
    antwoord = als_beheerder.get("/kalender/zoek?datum=onzin")
    assert "/kalender" in antwoord.headers["Location"]


def test_zoeken(als_gebruiker, rooster):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    wijzig_cellen([Wijziging(rooster["a"].id, MAANDAG, "code", "4"),
                   Wijziging(rooster["a"].id, MAANDAG, "eind", "16:00"),
                   Wijziging(rooster["b"].id, MAANDAG, "code", "7")])
    # Te korte naam zonder code
    assert "minimaal" in als_gebruiker.get("/zoeken/?naam=me").data.decode()
    pagina = als_gebruiker.get("/zoeken/?naam=tsa").data.decode()
    assert "Aantal diensten: 1" in pagina and "afwijkend" in pagina
    pagina = als_gebruiker.get("/zoeken/?code=7").data.decode()
    assert "Aantal diensten: 1" in pagina and "OB Vroeg" in pagina
    pagina = als_gebruiker.get("/zoeken/?naam=medewerker&van=2026-03-03").data.decode()
    assert "Aantal diensten: 0" in pagina
    csv = als_gebruiker.get("/zoeken/export.csv?naam=medewerker").data.decode("utf-8-sig")
    assert csv.count("\n") == 3 and "02-03-2026;10;TSA" in csv


def test_mijn_rooster_en_startpagina(client, rooster, klaar):
    from .conftest import login

    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.medewerker_id = rooster["a"].id
    db.session.commit()
    login(client, "collega")
    assert client.get("/").headers["Location"].endswith("/mijn")
    assert client.get("/mijn").status_code == 200


def test_logboek_scherm(als_beheerder, rooster):
    cel(als_beheerder, rooster["a"], MAANDAG, "code", "4")
    pagina = als_beheerder.get("/beheer/logboek?actie=Rooster+gewijzigd").data.decode()
    assert "Rooster gewijzigd" in pagina and "2026-W10" in pagina and "dienstcode" in pagina


def test_deellink(client, rooster, klaar):
    assert client.get("/deel/geheim/").status_code == 404
    instellingen.schrijf("deellink_actief", "1")
    instellingen.schrijf("deellink_token", "geheim-token")
    db.session.commit()
    assert client.get("/deel/fout/").status_code == 404
    pagina = client.get("/deel/geheim-token/?jaar=2026")
    assert pagina.status_code == 200 and "Overzicht 2026" not in pagina.data.decode()
    week = client.get("/deel/geheim-token/week/2026/10").data.decode()
    assert "Medewerker A" in week and "data-api-cellen" not in week
    # Via de deellink kan niets gewijzigd worden
    assert client.post("/api/cellen", json={"wijzigingen": []}).status_code == 401


# ---------- Eerst een voorbeeld, pas opslaan bij 'Opslaan' ----------

def test_voorbeeld_slaat_niets_op(als_beheerder, rooster):
    a = rooster["a"]
    antwoord = als_beheerder.post("/api/cellen", json={
        "opslaan": False,
        "wijzigingen": [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "4",
                         "versie": 0}],
        "dagopmerkingen": [{"datum": MAANDAG.isoformat(), "tekst": "Test"}],
    })
    gegevens = antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]
    # Het voorbeeld toont het resultaat ...
    assert (gegevens["dienstnaam"], gegevens["uren"], gegevens["weektotaal"]) == ("VW Vroeg", "8,00", "8,00")
    assert antwoord.json["dagopmerkingen"][MAANDAG.isoformat()]["tekst"] == "Test"
    # ... maar er is niets opgeslagen of gelogd
    assert dienst(a, MAANDAG) is None
    assert Dagopmerking.query.count() == 0
    assert Logboek.query.filter_by(actie="Rooster gewijzigd").count() == 0


def test_opslaan_in_een_keer(als_beheerder, rooster):
    a, b = rooster["a"], rooster["b"]
    antwoord = als_beheerder.post("/api/cellen", json={
        "opslaan": True,
        "wijzigingen": [
            {"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "4", "versie": 0},
            {"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "eind", "waarde": "1600", "versie": None},
            {"mw": b.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "99", "versie": 0},
        ],
        "dagopmerkingen": [{"datum": MAANDAG.isoformat(), "tekst": "Test"}],
    })
    assert antwoord.json["fouten"][0]["melding"] == "Onbekende dienstcode: 99"
    d = dienst(a, MAANDAG)
    assert (d.eind, d.uren_berekend) == ("16:00", 8.25)
    assert Dagopmerking.query.one().tekst == "Test"


def test_voorbeeld_met_ook_tonen_geeft_actuele_stand(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")
    # Na 'ongedaan maken' vraagt de browser de stand van een dag op zonder wijzigingen
    antwoord = als_beheerder.post("/api/cellen", json={
        "opslaan": False, "wijzigingen": [], "ook_tonen": [f"{a.id}|{MAANDAG.isoformat()}"],
        "ook_dagen": [MAANDAG.isoformat()]})
    assert antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]["code"] == "4"
    assert MAANDAG.isoformat() in antwoord.json["dagopmerkingen"]


def test_voorbeeld_meldt_conflict(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")  # versie is nu 1
    antwoord = als_beheerder.post("/api/cellen", json={
        "opslaan": False,
        "wijzigingen": [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code", "waarde": "5",
                         "versie": 0}]})
    assert antwoord.json["fouten"][0]["conflict"] is True


def test_weekpagina_heeft_opslaan_en_dialoog(als_beheerder, rooster):
    pagina = als_beheerder.get("/week/2026/10").data.decode()
    assert "data-opslaan" in pagina and 'id="niet-opgeslagen"' in pagina
    assert 'data-keuze="doorgaan"' in pagina and 'data-keuze="terug"' in pagina


def test_gebruiker_ziet_geen_opslaan(als_gebruiker, rooster):
    pagina = als_gebruiker.get("/week/2026/10").data.decode()
    assert "data-opslaan" not in pagina and "niet-opgeslagen" not in pagina


def test_zonder_expliciet_opslaan_wordt_niets_bewaard(als_beheerder, rooster):
    """Ook een oud (gecachet) script dat 'opslaan' niet meestuurt, kan niets opslaan."""
    a = rooster["a"]
    for extra in ({}, {"opslaan": "ja"}, {"opslaan": 1}, {"opslaan": False}):
        antwoord = als_beheerder.post("/api/cellen", json={
            "wijzigingen": [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "eind",
                             "waarde": "1600"}], **extra})
        assert antwoord.status_code == 200
    assert dienst(a, MAANDAG) is None
    # De oude route die dagopmerkingen direct opsloeg, bestaat niet meer
    assert als_beheerder.post("/api/dagopmerking", json={"datum": "2026-03-02"}).status_code == 404


def test_statische_bestanden_met_versienummer(als_beheerder, rooster):
    from app import VERSIE

    pagina = als_beheerder.get("/week/2026/10").data.decode()
    assert f"js/raster.js?v={VERSIE}" in pagina and f"css/style.css?v={VERSIE}" in pagina


def test_scriptversie_gelijk_aan_appversie():
    """raster.js controleert zelf of het bij de pagina hoort; de versies moeten gelijk zijn."""
    import pathlib
    import re

    from app import VERSIE

    script = (pathlib.Path(__file__).parent.parent / "app/static/js/raster.js").read_text()
    assert re.search(r'var SCRIPT_VERSIE = "([^"]+)"', script).group(1) == VERSIE


def test_cache_instructies(als_beheerder, rooster):
    from app import VERSIE

    pagina = als_beheerder.get("/week/2026/10")
    assert pagina.headers["Cache-Control"] == "no-store"
    assert 'data-versie="' + VERSIE + '"' in pagina.data.decode()
    api = als_beheerder.post("/api/cellen", json={"wijzigingen": []})
    assert api.headers["Cache-Control"] == "no-store"
    script = als_beheerder.get(f"/static/js/raster.js?v={VERSIE}")
    assert "max-age=31536000" in script.headers["Cache-Control"]
    assert als_beheerder.get("/static/js/raster.js").headers["Cache-Control"] == "no-cache"


def test_maar_een_opslaan_knop(als_beheerder, rooster):
    pagina = als_beheerder.get("/week/2026/10").data.decode()
    assert pagina.count("data-opslaan") == 1


# ---------- Twee diensten per dag (1.4.0) ----------

def diensten(mw, datum):
    """{volgnummer: Dienst} van een medewerker op een dag."""
    db.session.expire_all()
    return {d.volgnummer: d for d in Dienst.query.filter_by(medewerker_id=mw.id, datum=datum)}


def cellen(client, wijzigingen, opslaan=True):
    return client.post("/api/cellen", json={"wijzigingen": wijzigingen, "opslaan": opslaan})


@pytest.mark.parametrize("invoer", ["17/3", "17+3", "17 3", " 17 / 3 "])
def test_twee_codes_in_het_code_raster(als_beheerder, rooster, invoer):
    a = rooster["a"]
    antwoord = cel(als_beheerder, a, MAANDAG, "code", invoer)
    assert antwoord.status_code == 200 and antwoord.json["fouten"] == []
    per_vn = diensten(a, MAANDAG)
    assert set(per_vn) == {1, 2}
    assert (per_vn[1].dienstnaam, per_vn[1].begin, per_vn[1].eind, per_vn[1].uren_berekend) == \
        ("BHV", "08:30", "12:30", 4.0)
    assert (per_vn[2].dienstnaam, per_vn[2].begin, per_vn[2].eind, per_vn[2].uren_berekend) == \
        ("VW Avond", "14:30", "23:00", 8.0)
    gegevens = antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]
    assert gegevens["code"] == "17/3" and gegevens["dienstnaam"] == "BHV"
    assert gegevens["tweede"]["dienstnaam"] == "VW Avond" and gegevens["tweede"]["uren"] == "8,00"
    assert gegevens["weektotaal"] == "12,00"  # beide diensten tellen mee
    # Gesplitste achtergrond in het code-raster: links dienst 1, rechts dienst 2
    assert "linear-gradient(90deg,#E2EFDA 50%,#FFFF00 50%)" in gegevens["code_stijl"]
    assert antwoord.json["waarschuwingen"] == []


def test_een_code_of_leeg_wist_de_tweede_dienst(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    cel(als_beheerder, a, MAANDAG, "code", "4")
    per_vn = diensten(a, MAANDAG)
    assert set(per_vn) == {1} and per_vn[1].dienstnaam == "VW Vroeg"
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    cel(als_beheerder, a, MAANDAG, "code", "")
    assert diensten(a, MAANDAG) == {}
    # Ook een vrije dienstnaam en eigen tijden van dienst 2 verdwijnen bij leeg
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "dienstnaam",
                            "volgnummer": 2, "waarde": "Controleronde"}])
    cel(als_beheerder, a, MAANDAG, "code", "")
    assert diensten(a, MAANDAG) == {}


def test_ongeldige_dubbele_invoer_wijzigt_niets(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "4")
    for invoer, melding in (("4/7/9", "Hooguit 2 diensten"), ("4/99", "Onbekende dienstcode: 99"),
                            ("4/x", "geen dienstcode")):
        antwoord = cel(als_beheerder, a, MAANDAG, "code", invoer)
        assert melding in antwoord.json["fouten"][0]["melding"]
        assert antwoord.json["fouten"][0]["vn"] == 1  # hoort bij de cel in het code-raster
        per_vn = diensten(a, MAANDAG)
        assert set(per_vn) == {1} and per_vn[1].dienstnaam == "VW Vroeg"


def test_alleen_een_tweede_dienst(als_beheerder, rooster):
    a = rooster["a"]
    antwoord = cel(als_beheerder, a, MAANDAG, "code", "/3")
    assert set(diensten(a, MAANDAG)) == {2}
    assert antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]["code"] == "/3"


def test_tweede_dienst_eigen_tijden_uren_en_logboek(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    antwoord = cellen(als_beheerder, [
        {"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "eind", "volgnummer": 2, "waarde": "2200"}])
    assert antwoord.json["fouten"] == []
    per_vn = diensten(a, MAANDAG)
    assert per_vn[1].eind == "12:30" and per_vn[1].uren_berekend == 4.0  # dienst 1 ongemoeid
    assert per_vn[2].eind == "22:00" and per_vn[2].tijden_handmatig and per_vn[2].uren_berekend == 7.0
    gegevens = antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]
    assert gegevens["tweede"]["handmatig"] and gegevens["weektotaal"] == "11,00"
    regel = Logboek.query.filter_by(actie="Rooster gewijzigd").order_by(Logboek.id.desc()).first()
    assert regel.veld == "dienst 2: eindtijd"
    assert (regel.oude_waarde, regel.nieuwe_waarde) == ("23:00", "22:00")
    # Het aanmaken van dienst 2 via het code-raster staat ook als 'dienst 2' in het logboek
    assert Logboek.query.filter_by(veld="dienst 2: dienstcode", nieuwe_waarde="3").count() == 1
    # Eigen uren bij dienst 2
    cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "uren", "volgnummer": 2,
                            "waarde": "5"}])
    assert diensten(a, MAANDAG)[2].uren_berekend == 5.0


def test_dienst2_heeft_geen_opmerking(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    antwoord = cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "opmerking",
                                       "volgnummer": 2, "waarde": "Locatie A"}])
    assert antwoord.json["fouten"][0]["melding"] == "Dit veld bestaat niet bij deze dienst."
    assert cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code",
                                   "volgnummer": 3, "waarde": "4"}]).status_code == 400


def test_overlappende_diensten_geven_waarschuwing(als_beheerder, rooster):
    a = rooster["a"]
    antwoord = cel(als_beheerder, a, MAANDAG, "code", "4/7")  # 07:15-15:45 en 07:30-16:00
    assert antwoord.json["fouten"] == []  # niet tegenhouden
    assert set(diensten(a, MAANDAG)) == {1, 2}
    assert antwoord.json["waarschuwingen"] == [{
        "mw": a.id, "datum": MAANDAG.isoformat(),
        "melding": "Let op: de twee diensten van TSA op 02-03 overlappen in tijd."}]


def test_overlap_berekening():
    from app.services.weekrooster import overlappen

    def d(begin, eind):
        return Dienst(begin=begin, eind=eind)

    assert overlappen(d("07:00", "15:00"), d("14:00", "22:00"))
    assert not overlappen(d("07:00", "15:00"), d("15:00", "23:00"))  # aansluitend mag
    assert overlappen(d("22:00", "06:00"), d("23:00", "23:30"))  # nachtdienst
    assert not overlappen(d("22:00", "06:00"), d("05:00", "08:00"))  # ochtend vóór de nachtdienst
    assert not overlappen(d("07:00", "15:00"), d(None, None))  # zonder tijden geen overlap
    assert not overlappen(d("07:00", "15:00"), None)


def test_optimistic_locking_per_dienst(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    versie1, versie2 = diensten(a, MAANDAG)[1].versie, diensten(a, MAANDAG)[2].versie
    # Iemand anders wijzigt dienst 2
    cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "eind", "volgnummer": 2,
                            "waarde": "22:00"}])
    # Wijziging van dienst 1 met de oude versie van dienst 1: mag (dienst 1 is niet gewijzigd)
    antwoord = cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "begin",
                                       "waarde": "08:00", "versie": versie1}])
    assert antwoord.json["fouten"] == []
    # Wijziging van dienst 2 met de oude versie van dienst 2: conflict
    antwoord = cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "eind",
                                       "volgnummer": 2, "waarde": "21:00", "versie": versie2}])
    assert antwoord.json["fouten"][0]["conflict"] and antwoord.json["fouten"][0]["vn"] == 2
    assert diensten(a, MAANDAG)[2].eind == "22:00"
    # Een code in het code-raster controleert ook de versie van dienst 2 (versie2)
    antwoord = cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code",
                                       "waarde": "4", "versie": diensten(a, MAANDAG)[1].versie,
                                       "versie2": versie2}])
    assert antwoord.json["fouten"][0]["conflict"]
    assert 2 in diensten(a, MAANDAG)  # dienst 2 is niet gewist


def test_voorbeeld_van_twee_diensten_slaat_niets_op(als_beheerder, rooster):
    a = rooster["a"]
    antwoord = cellen(als_beheerder, [{"mw": a.id, "datum": MAANDAG.isoformat(), "veld": "code",
                                       "waarde": "17/3"}], opslaan=False)
    assert antwoord.json["bijgewerkt"][f"{a.id}|{MAANDAG.isoformat()}"]["tweede"]["dienstnaam"] == "VW Avond"
    assert diensten(a, MAANDAG) == {}


def test_weekpagina_toont_tweede_dienst(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    pagina = als_beheerder.get("/week/2026/10").data.decode()
    assert ">17/3</td>" in pagina  # code-raster
    assert f'<tr class="r-e tweede-rij" data-tweede="{a.id}">' in pagina  # zichtbaar
    assert f'<tr class="r-e tweede-rij" data-tweede="{rooster["b"].id}" hidden>' in pagina
    assert 'data-vn="2" data-toon="dienstnaam"' in pagina and "VW Avond" in pagina
    # Printversie: ook beide diensten
    assert f'<tr class="p-e" data-ptweede="{a.id}">' in pagina
    assert pagina.count('data-pvn="2" data-p="dienstnaam"') == 14  # 2 medewerkers x 7 dagen


def test_gebruiker_ziet_tweede_dienst_maar_kan_niets_wijzigen(app, client, rooster, klaar):
    from .conftest import login

    a = rooster["a"]
    planner = app.test_client()
    login(planner, "beheerder")
    cel(planner, a, MAANDAG, "code", "17/3")
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.medewerker_id = a.id
    db.session.commit()
    login(client, "collega")
    pagina = client.get("/week/2026/10").data.decode()
    assert "VW Avond" in pagina and "BHV" in pagina and "code-paneel" not in pagina
    assert cel(client, a, MAANDAG, "code", "4").status_code in (302, 403)
    assert set(diensten(a, MAANDAG)) == {1, 2}


def test_mijn_rooster_toont_beide_diensten(app, client, rooster, klaar):
    from app.services import klok

    from .conftest import login

    a = rooster["a"]
    vandaag = klok.vandaag()
    planner = app.test_client()
    login(planner, "beheerder")
    cel(planner, a, vandaag, "code", "17/3")
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.medewerker_id = a.id
    db.session.commit()
    login(client, "collega")
    pagina = client.get("/mijn").data.decode()
    vandaag_blok = pagina.split('data-blok="vandaag"')[1].split("</section>")[0]
    assert "BHV" in vandaag_blok and "VW Avond" in vandaag_blok
    assert "(2e dienst)" in pagina


def test_week_kopieren_neemt_beide_diensten_mee(als_beheerder, rooster):
    a = rooster["a"]
    cel(als_beheerder, a, MAANDAG, "code", "17/3")
    cel(als_beheerder, a, date(2026, 3, 16), "code", "4/7")  # doelweek had al twee diensten
    cel(als_beheerder, a, date(2026, 3, 17), "code", "4/7")
    als_beheerder.post("/week/2026/10/kopieer", data={"naar": "2026-W12", "medewerker_id": ""})
    kopie = diensten(a, date(2026, 3, 16))
    assert (kopie[1].dienstnaam, kopie[2].dienstnaam) == ("BHV", "VW Avond")
    assert kopie[2].uren_berekend == 8.0
    assert diensten(a, date(2026, 3, 17)) == {}  # bron leeg: doel ook leeg (beide diensten)
