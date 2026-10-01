"""Hulp voor de browsertests (Playwright): een echte server met fictieve testdata.

De server draait in een thread (Werkzeug), met CSRF-bescherming aan, op een eigen
datamap. Alle namen en gegevens zijn verzonnen.

Chromium: standaard de browser van Playwright zelf. Staat er een vooraf geïnstalleerde
Chromium in /opt/pw-browsers/chromium (of in PLAYWRIGHT_CHROMIUM), dan die.
"""

import os
import threading
from datetime import date, timedelta

import pytest
from werkzeug.serving import make_server

from app import create_app
from app.config import Config

WACHTWOORD = "testwachtwoord123"

# Doelschermen: naam -> (breedte, hoogte, telefoon/tablet?)
SCHERMEN = {
    "360x640": (360, 640, True),
    "375x667": (375, 667, True),
    "390x844": (390, 844, True),
    "412x915": (412, 915, True),
    "844x390": (844, 390, True),
    "768x1024": (768, 1024, True),
    "1280x800": (1280, 800, False),
}

NAMEN = [
    "Anna de Vries-van Bergen", "Bram Jansen", "Chantal Bakker", "Daan Visser", "Eva Smit",
    "Fleur Meijer", "Gijs de Boer", "Hanna Mulder", "Ivo de Groot", "Julia Bos",
    "Koen Vos", "Lotte Peters", "Milan Hendriks", "Noor van Dijk", "Olaf Kok",
]


class BrowserConfig(Config):
    """Zoals productie (CSRF aan), maar met een eigen datamap."""

    def __init__(self, data_map: str) -> None:
        os.environ["DATA_MAP"] = data_map
        super().__init__()
        self.SECRET_KEY = "browsertest-geheim"
        self.SESSION_COOKIE_SECURE = False


def chromium_pad() -> str | None:
    pad = os.environ.get("PLAYWRIGHT_CHROMIUM") or "/opt/pw-browsers/chromium"
    return pad if os.path.exists(pad) else None


def vul_testdata(vandaag: date) -> dict:
    """15 medewerkers, voorbeeldcodes en een vol jaar aan diensten rond vandaag."""
    from flask_migrate import upgrade

    from app.extensions import db
    from app.models import Contracturen, Dagopmerking, Dienst, Dienstcode, Medewerker, Vakantie
    from app.services import instellingen, logboek
    from app.services.rooster import herbereken_alle
    from app.services.voorbeeldpakket import laad_voorbeeldpakket
    from app.services.wachtwoorden import hash_wachtwoord

    upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    instellingen.schrijf("setup_voltooid", "1")
    instellingen.schrijf("teamnaam", "Team Fictief")
    laad_voorbeeldpakket()
    codes = Dienstcode.query.filter(Dienstcode.std_begin.isnot(None)).order_by(Dienstcode.nummer).all()

    medewerkers = []
    for i, naam in enumerate(NAMEN):
        medewerker = Medewerker(naam=naam, initialen=f"T{i:02d}", volgorde=i,
                                functie_opmerking="Teamleider" if i == 0 else "")
        db.session.add(medewerker)
        db.session.flush()
        db.session.add(Contracturen(medewerker_id=medewerker.id, jaar=vandaag.year, uren=1500))
        medewerkers.append(medewerker)
    eerste = date(vandaag.year, 1, 1)
    for i, medewerker in enumerate(medewerkers):
        for d in range(366):
            dag = eerste + timedelta(days=d)
            if dag.year != vandaag.year or (d + i) % 7 in (5, 6):
                continue  # twee vrije dagen per week
            code = codes[(d + i) % len(codes)]
            db.session.add(Dienst(
                medewerker_id=medewerker.id, datum=dag, dienstcode_id=code.id,
                begin=code.std_begin, eind=code.std_eind,
                opmerking_tekst="Locatie A" if (d + i) % 4 == 0 else "",
                opmerking_begin="08:00" if (d + i) % 8 == 0 else None,
                opmerking_eind="09:00" if (d + i) % 8 == 0 else None))
    db.session.add(Vakantie(naam="Herfstvakantie", datum_van=date(vandaag.year, 10, 17),
                            datum_tot=date(vandaag.year, 10, 25)))
    db.session.add(Dagopmerking(datum=vandaag, tekst="Oefening ontruiming", handmatig=True))
    for gebruikersnaam, rol, medewerker in (("beheerder", "beheerder", medewerkers[1]),
                                             ("collega", "gebruiker", medewerkers[0])):
        from app.models import Gebruiker

        db.session.add(Gebruiker(gebruikersnaam=gebruikersnaam, weergavenaam=gebruikersnaam.title(),
                                 wachtwoord_hash=hash_wachtwoord(WACHTWOORD), rol=rol,
                                 medewerker_id=medewerker.id))
    for i in range(30):
        logboek.log("Dienst gewijzigd", f"Testregel {i}", datum=vandaag, medewerker=NAMEN[i % 15],
                    veld="code", oud="4", nieuw="5", gebruiker="beheerder", rol="beheerder")
    db.session.commit()
    herbereken_alle()
    db.session.commit()
    return {"medewerkers": [m.id for m in medewerkers]}


class Server:
    """Echte webserver met de app, in een achtergrondthread."""

    def __init__(self, data_map: str) -> None:
        from app.services import klok

        self.app = create_app(BrowserConfig(data_map))
        with self.app.app_context():
            self.gegevens = vul_testdata(klok.vandaag())
        self._server = make_server("127.0.0.1", 0, self.app, threaded=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()


# ---------------------------------------------------------------------------
# Fixtures (via tests/conftest.py beschikbaar in alle browsertests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server(tmp_path_factory):
    server = Server(str(tmp_path_factory.mktemp("browserdata")))
    yield server
    server.stop()


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(executable_path=chromium_pad())
            except Exception as fout:  # geen Chromium geïnstalleerd
                if os.environ.get("BROWSERTESTS") == "verplicht":
                    raise
                pytest.skip(f"Chromium niet beschikbaar: {fout}")
            yield browser
            browser.close()
    except pytest.skip.Exception:
        raise


@pytest.fixture(scope="module")
def sessies(server, browser):
    """Ingelogde sessie (cookies) per rol, één keer inloggen."""
    staten = {}
    for rol in ("collega", "beheerder"):
        context = browser.new_context()
        pagina = context.new_page()
        pagina.goto(server.url + "/login")
        pagina.fill("input[name=gebruikersnaam]", rol)
        pagina.fill("input[name=wachtwoord]", WACHTWOORD)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda url: "/login" not in url)
        staten[rol] = context.storage_state()
        context.close()
    return staten


def nieuwe_pagina(browser, scherm: str, staat=None):
    breedte, hoogte, mobiel = SCHERMEN[scherm]
    context = browser.new_context(viewport={"width": breedte, "height": hoogte}, is_mobile=mobiel,
                                  has_touch=mobiel, device_scale_factor=2 if mobiel else 1,
                                  storage_state=staat, locale="nl-NL")
    return context, context.new_page()


