"""Pauzeaftrek instelbaar in Beheer → Instellingen (Deel 2, versie 1.6.0).

Standaard precies de oude Excel-VBA: meer dan 5,5 uur gewerkt -> 0,5 uur pauze eraf.
"""

from datetime import date

import pytest

from app.extensions import db
from app.models import Dienst, Logboek, Medewerker
from app.services import instellingen
from app.services.rooster import UrenContext, herbereken_alle, uren_voor
from app.services.urenberekening import STANDAARD_PAUZE, bereken_uren, pauze_aftrek

MAANDAG = date(2026, 3, 2)


# ---------------------------------------------------------------------------
# De berekening zelf
# ---------------------------------------------------------------------------

def test_standaard_is_het_oude_gedrag():
    assert STANDAARD_PAUZE == ((5.5, 0.5),)
    assert bereken_uren("07:15", "15:45") == 8.0  # 8,5 - 0,5
    assert bereken_uren("08:00", "13:30") == 5.5  # precies 5,5: geen pauze
    assert bereken_uren("07:15", "15:45", pauze=STANDAARD_PAUZE) == 8.0


def test_pauze_uit():
    assert bereken_uren("07:15", "15:45", pauze=()) == 8.5
    assert bereken_uren("22:00", "06:30", pauze=()) == 8.5


@pytest.mark.parametrize("begin, eind, verwacht", [
    ("06:00", "11:00", 5.0),    # 5 uur: geen pauze
    ("06:00", "12:00", 5.5),    # 6 uur: > 5,5 -> 0,5
    ("06:00", "15:00", 8.5),    # precies 9 uur: nog de eerste regel
    ("06:00", "15:15", 8.5),    # 9,25 uur: > 9 -> 0,75 (niet opgeteld: geen 1,25)
    ("06:00", "18:00", 11.25),  # 12 uur: hoogste regel telt
])
def test_meerdere_staffels(begin, eind, verwacht):
    staffel = ((5.5, 0.5), (9.0, 0.75))
    assert bereken_uren(begin, eind, pauze=staffel) == verwacht


def test_precies_op_de_grens_telt_niet():
    assert pauze_aftrek(9.0, ((5.5, 0.5), (9.0, 0.75))) == 0.5
    assert pauze_aftrek(9.01, ((5.5, 0.5), (9.0, 0.75))) == 0.75
    assert pauze_aftrek(5.5, ((5.5, 0.5),)) == 0
    assert pauze_aftrek(4, ((5.5, 0.5),)) == 0
    assert pauze_aftrek(10, ()) == 0


def test_grens_vergelijkt_als_de_vba(app):
    """Precies op de grens telt niet, maar net als in de VBA met het kommagetal van de tijden.

    08:00-13:30 is als kommagetal precies 5,5 (geen pauze); 13:00-18:30 wordt 5,500...02 en
    krijgt in de VBA, en dus in de app, wél pauze. Zo blijven bestaande uren gelijk.
    """
    assert bereken_uren("08:00", "13:30") == 5.5
    assert bereken_uren("13:00", "18:30") == 5.0
    staffel = ((5.5, 0.5), (9.0, 0.75))
    assert bereken_uren("06:00", "15:00", pauze=staffel) == 8.5  # 9,0 precies
    assert bereken_uren("08:00", "17:00", pauze=staffel) == 8.25  # 9,000...02: zoals de VBA zou doen


def test_pauze_per_dienst_ook_bij_twee_diensten(app, klaar):
    from app.services.voorbeeldpakket import laad_voorbeeldpakket
    from app.services.weekrooster import Wijziging, wijzig_cellen

    laad_voorbeeldpakket()
    mw = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(mw)
    db.session.commit()
    instellingen.schrijf("pauze", instellingen.pauze_json(True, [(5.5, 0.5), (9, 0.75)]))
    db.session.commit()
    # 4 = VW Vroeg 07:15-15:45 (8,5 uur), 3 = VW Avond 14:30-23:00 (8,5 uur): elk 0,5 eraf
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4/3")])[1] == []
    per_vn = {d.volgnummer: d.uren_berekend for d in Dienst.query.filter_by(medewerker_id=mw.id)}
    assert per_vn == {1: 8.0, 2: 8.0}


# ---------------------------------------------------------------------------
# De instelling (opslag in één sleutel, als JSON)
# ---------------------------------------------------------------------------

def test_instelling_standaard_en_onleesbaar(app):
    assert instellingen.pauze_instelling() == {"aan": True, "regels": [(5.5, 0.5)]}
    assert instellingen.pauze() == STANDAARD_PAUZE
    instellingen.schrijf("pauze", "dit is geen json")
    assert instellingen.pauze() == STANDAARD_PAUZE  # nooit een fout bij het rekenen
    instellingen.schrijf("pauze", instellingen.pauze_json(False, [(5.5, 0.5)]))
    assert instellingen.pauze() == ()
    assert instellingen.pauze_instelling()["regels"] == [(5.5, 0.5)]  # bewaard voor later


@pytest.mark.parametrize("regels, melding", [
    ([("5,5", "0,5"), ("5,5", "0,75")], "oplopend"),
    ([("9", "0,75"), ("5,5", "0,5")], "oplopend"),
    ([("5,5", "6")], "kleiner dan"),
    ([("5,5", "5,5")], "kleiner dan"),
    ([("-1", "0")], "0 of meer"),
    ([("inf", "0,5")], "getal"),
    ([("abc", "0,5")], "getal"),
    ([("5,5", "")], "beide"),
    ([("25", "0,5")], "24"),
    ([], "minstens één"),
])
def test_ongeldige_staffels(regels, melding):
    _, fouten = instellingen.controleer_pauze(True, regels)
    assert fouten and melding in " ".join(fouten)


def test_geldige_staffel_en_lege_regels():
    waarde, fouten = instellingen.controleer_pauze(True, [("5,5", "0,5"), ("", ""), ("9", "0.75")])
    assert fouten == [] and waarde == {"aan": True, "regels": [(5.5, 0.5), (9.0, 0.75)]}
    waarde, fouten = instellingen.controleer_pauze(False, [])  # uit mag zonder regels
    assert fouten == [] and waarde == {"aan": False, "regels": []}
    _, fouten = instellingen.controleer_pauze(True, [("1", "0")] * 6)
    assert "hooguit 5" in " ".join(fouten)


# ---------------------------------------------------------------------------
# Beheer → Instellingen en herberekenen
# ---------------------------------------------------------------------------

def _formulier(**pauze):
    gegevens = {s: instellingen.lees(s) for s in instellingen.STANDAARD if s != "pauze"}
    gegevens.update({"eerste_jaar": "2026", "pauze_formulier": "1"})
    for vink in ("deellink_actief", "opmerkingtijden_meetellen"):
        gegevens.pop(vink)
    gegevens.update(pauze)
    return gegevens


def test_scherm_toont_blok_pauze(app, als_beheerder):
    tekst = als_beheerder.get("/beheer/instellingen").data.decode()
    assert "Pauze" in tekst and 'name="pauze_aan"' in tekst and 'name="pauze_grens_1"' in tekst
    assert 'value="5,5"' in tekst and 'value="0,5"' in tekst


def test_scherm_opslaan_met_logboek_en_tip(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/instellingen", data=_formulier(
        pauze_aan="1", pauze_grens_1="5,5", pauze_aftrek_1="0,5", pauze_grens_2="9", pauze_aftrek_2="0,75"),
        follow_redirects=True)
    assert antwoord.status_code == 200
    assert instellingen.pauze() == ((5.5, 0.5), (9.0, 0.75))
    assert "Alle uren herberekenen" in antwoord.data.decode()
    regel = Logboek.query.filter_by(actie="Instelling gewijzigd", veld="pauze").one()
    assert regel.oude_waarde == "aan: meer dan 5,5 uur: 0,5 eraf"
    assert regel.nieuwe_waarde == "aan: meer dan 5,5 uur: 0,5 eraf; meer dan 9 uur: 0,75 eraf"


def test_scherm_ongeldig_geeft_melding_en_slaat_niets_op(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/instellingen", data=_formulier(
        pauze_aan="1", pauze_grens_1="9", pauze_aftrek_1="0,5", pauze_grens_2="5,5", pauze_aftrek_2="0,5"))
    assert antwoord.status_code == 400 and "oplopend" in antwoord.data.decode()
    assert instellingen.pauze() == STANDAARD_PAUZE


def test_scherm_pauze_uit(app, als_beheerder):
    als_beheerder.post("/beheer/instellingen", data=_formulier(pauze_grens_1="5,5", pauze_aftrek_1="0,5"))
    assert instellingen.pauze() == ()


def test_formulier_zonder_pauzeblok_laat_de_pauze_ongemoeid(app, als_beheerder):
    gegevens = _formulier()
    del gegevens["pauze_formulier"]
    assert als_beheerder.post("/beheer/instellingen", data=gegevens).status_code == 302
    assert instellingen.pauze() == STANDAARD_PAUZE


def test_herberekenen_na_wijziging(app, klaar):
    mw = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(mw)
    db.session.flush()
    dienst = Dienst(medewerker_id=mw.id, datum=MAANDAG, begin="07:00", eind="17:00", uren_berekend=9.5,
                    dienstnaam_override="Dagdienst")
    db.session.add(dienst)
    db.session.commit()
    instellingen.schrijf("pauze", instellingen.pauze_json(True, [(5.5, 0.5), (9, 0.75)]))
    db.session.commit()
    assert dienst.uren_berekend == 9.5  # nog niet herberekend
    assert herbereken_alle() == 1
    assert dienst.uren_berekend == 9.25
    assert uren_voor(dienst, UrenContext(MAANDAG, MAANDAG)) == 9.25
    instellingen.schrijf("pauze", instellingen.pauze_json(False, [(5.5, 0.5)]))
    db.session.commit()
    assert herbereken_alle() == 1 and dienst.uren_berekend == 10.0


def test_opmerkingtijden_krijgen_ook_de_staffel(app, klaar):
    instellingen.schrijf("opmerkingtijden_meetellen", "1")
    instellingen.schrijf("pauze", instellingen.pauze_json(False, []))
    db.session.commit()
    dienst = Dienst(datum=MAANDAG, begin="07:00", eind="13:00", opmerking_begin="13:00",
                    opmerking_eind="19:00")
    assert uren_voor(dienst, UrenContext(MAANDAG, MAANDAG)) == 12.0  # zonder pauze 6 + 6
