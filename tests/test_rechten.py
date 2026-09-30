"""Rechten: een gewone gebruiker mag NIETS wijzigen (HTTP 403), ook niet via de API.

De test loopt automatisch langs ALLE routes die schrijvende methodes accepteren.
Komt er later een nieuwe route bij, dan wordt die dus vanzelf mee getest.
"""

from app import GEBRUIKER_MAG_SCHRIJVEN
from app.models import Gebruiker, Medewerker

SCHRIJVEND = {"POST", "PUT", "PATCH", "DELETE"}


def _url_voor(regel) -> str:
    """Maak een URL voor een route door alle variabelen met '1' te vullen."""
    url = regel.rule
    for naam in regel.arguments:
        url = url.replace(f"<int:{naam}>", "1").replace(f"<{naam}>", "1")
        url = url.replace(f"<string:{naam}>", "1").replace(f"<path:{naam}>", "1")
    return url


def _schrijvende_routes(app):
    for regel in app.url_map.iter_rules():
        methodes = (regel.methods or set()) & SCHRIJVEND
        if methodes and regel.endpoint not in GEBRUIKER_MAG_SCHRIJVEN:
            for methode in methodes:
                yield regel, methode


def test_gebruiker_krijgt_403_op_elke_schrijvende_route(app, als_gebruiker):
    # Zorg dat er een medewerker en gebruiker met id 1 bestaan
    from app.extensions import db

    db.session.add(Medewerker(naam="Medewerker A", initialen="TSA"))
    db.session.commit()

    routes = list(_schrijvende_routes(app))
    assert len(routes) > 10, "Er horen veel schrijvende routes te zijn"
    for regel, methode in routes:
        antwoord = als_gebruiker.open(_url_voor(regel), method=methode, data={})
        assert antwoord.status_code == 403, f"{methode} {regel.rule} gaf {antwoord.status_code}"


def test_niet_ingelogd_mag_niets_schrijven(app, client, klaar):
    for regel, methode in _schrijvende_routes(app):
        antwoord = client.open(_url_voor(regel), method=methode, data={})
        assert antwoord.status_code in (401, 403), f"{methode} {regel.rule}"


def test_gebruiker_ziet_geen_beheerschermen(app, als_gebruiker):
    for regel in app.url_map.iter_rules():
        if regel.endpoint.startswith("beheer.") and "GET" in regel.methods:
            antwoord = als_gebruiker.get(_url_voor(regel))
            assert antwoord.status_code == 403, f"GET {regel.rule}"


def test_gebruiker_wijzigt_niets_in_database(app, als_gebruiker, klaar):
    als_gebruiker.post("/beheer/gebruikers/nieuw", data={
        "gebruikersnaam": "indringer", "weergavenaam": "X", "rol": "beheerder",
        "wachtwoord": "heelgeheim123", "actief": "1"})
    assert Gebruiker.query.filter_by(gebruikersnaam="indringer").first() is None


def test_beheerder_mag_beheerschermen_zien(als_beheerder):
    for url in ["/beheer/", "/beheer/medewerkers", "/beheer/dienstcodes", "/beheer/vakanties",
                "/beheer/feestdagen", "/beheer/gebruikers", "/beheer/instellingen",
                "/beheer/herberekenen", "/beheer/medewerkers/nieuw", "/beheer/dienstcodes/nieuw",
                "/beheer/gebruikers/nieuw"]:
        assert als_beheerder.get(url).status_code == 200, url
