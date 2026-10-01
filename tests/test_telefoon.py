"""Telefoonweergave (server-kant): 'Mijn rooster' en de mobiele weekweergave.

Het gedrag in de browser (vegen, bottom sheet, opslaan) staat in tests/test_mobiel_bewerken.py.
"""

import re
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import Dienst, Dienstcode, Gebruiker, Medewerker
from app.services import klok
from app.services.voorbeeldpakket import laad_voorbeeldpakket

from .conftest import login

VANDAAG = date(2026, 3, 4)  # woensdag, week 10


@pytest.fixture
def vaste_dag(monkeypatch):
    monkeypatch.setattr(klok, "vandaag", lambda: VANDAAG)
    return VANDAAG


@pytest.fixture
def collega_met_rooster(client, klaar, vaste_dag):
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA", volgorde=1, ics_token="geheim-ics")
    db.session.add(medewerker)
    db.session.commit()
    code = Dienstcode.query.filter_by(nummer=4).one()
    for dagen, opmerking in ((0, "Locatie A"), (2, "")):
        db.session.add(Dienst(medewerker_id=medewerker.id, datum=VANDAAG + timedelta(days=dagen),
                              dienstcode_id=code.id, begin="07:15", eind="15:45", uren_berekend=8.0,
                              opmerking_tekst=opmerking))
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.medewerker_id = medewerker.id
    db.session.commit()
    login(client, "collega")
    return medewerker


def _blok(pagina: str, naam: str) -> str:
    """Inhoud van <section data-blok="naam">."""
    gevonden = re.search(rf'<section[^>]*data-blok="{naam}"[^>]*>(.*?)</section>', pagina, re.S)
    assert gevonden, f"blok {naam} ontbreekt"
    return gevonden.group(1)


def test_mijn_rooster_vandaag_en_volgende_dienst(client, collega_met_rooster):
    pagina = client.get("/mijn").get_data(as_text=True)
    vandaag = _blok(pagina, "vandaag")
    assert "VW Vroeg" in vandaag and "07:15" in vandaag and "15:45" in vandaag and "Locatie A" in vandaag
    volgende = _blok(pagina, "volgende")
    assert "vrijdag" in volgende and "06-03-2026" in volgende


def test_mijn_rooster_vandaag_vrij(client, collega_met_rooster, monkeypatch):
    monkeypatch.setattr(klok, "vandaag", lambda: VANDAAG + timedelta(days=1))
    pagina = client.get("/mijn").get_data(as_text=True)
    assert "Geen dienst" in _blok(pagina, "vandaag")
    assert "06-03-2026" in _blok(pagina, "volgende")


def test_mijn_rooster_kaart_per_dag(client, collega_met_rooster):
    pagina = client.get("/mijn").get_data(as_text=True)
    kaarten = re.findall(r'<li class="mijn-dag[^"]*"', pagina)
    assert len(kaarten) == 2
    assert 'class="mijn-dag vandaag"' in pagina


def test_mijn_rooster_knop_toevoegen_aan_agenda(client, collega_met_rooster):
    pagina = client.get("/mijn").get_data(as_text=True)
    knop = re.search(r'<a [^>]*data-agenda-knop[^>]*>', pagina).group(0)
    assert 'href="webcal://localhost/ics/geheim-ics.ics"' in knop
    assert "Toevoegen aan mijn agenda" in pagina


def test_mijn_rooster_zonder_ics_token_verwijst_naar_uitleg(client, collega_met_rooster):
    collega_met_rooster.ics_token = ""
    db.session.commit()
    pagina = client.get("/mijn").get_data(as_text=True)
    knop = re.search(r'<a [^>]*data-agenda-knop[^>]*>', pagina).group(0)
    assert 'href="/mijn/agenda"' in knop


# ---------------------------------------------------------------------------
# Weekrooster: mobiele weergave (dag- en medewerkerweergave)
# ---------------------------------------------------------------------------

def test_week_heeft_mobiele_weergave_met_dag_en_medewerker(client, collega_met_rooster):
    pagina = client.get("/week/2026/10").get_data(as_text=True)
    assert "data-week-mobiel" in pagina
    # Zeven dagpagina's en één pagina per medewerker
    assert len(re.findall(r'data-dagpagina="\d"', pagina)) == 7
    assert len(re.findall(r'data-mwpagina="\d+"', pagina)) == 1
    # De dag 'vandaag' is de beginpagina
    assert 'data-start-dag="2"' in pagina
    assert "data-weergave-wissel" in pagina


def test_week_mobiel_collega_kan_niet_bewerken(client, collega_met_rooster):
    pagina = client.get("/week/2026/10").get_data(as_text=True)
    assert "data-bewerk-dag" not in pagina and 'id="dienst-paneel"' not in pagina


def test_week_mobiel_beheerder_kan_dag_bewerken(als_beheerder, klaar, vaste_dag):
    laad_voorbeeldpakket()
    db.session.add(Medewerker(naam="Medewerker A", initialen="TSA", volgorde=1))
    db.session.commit()
    pagina = als_beheerder.get("/week/2026/10").get_data(as_text=True)
    assert pagina.count("data-bewerk-dag") == 14  # 7 dagen x 2 weergaven
    paneel = re.search(r'<dialog id="dienst-paneel".*?</dialog>', pagina, re.S).group(0)
    # Keuzelijst met dienstcodes en omschrijving, tijdvelden, opmerking, eigen uren
    assert '<option value="4">4 – VW Vroeg (07:15–15:45)</option>' in paneel
    for veld in ("begin", "eind", "opm_begin", "opm_eind"):
        assert re.search(rf'<input type="time" name="{veld}"', paneel), veld
    assert 'name="opmerking"' in paneel and 'name="uren"' in paneel
    assert "data-paneel-uren" in paneel  # voorbeeld van de uren
