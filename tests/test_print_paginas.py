"""Browsertests (Playwright): hoeveel pagina's de print van het weekrooster wordt (1.4.4).

- tot en met 10 medewerkers altijd één A4, ook met overal twee diensten, lange namen en
  dagopmerkingen; 13 met twee diensten ook (kleinere letters);
- meer medewerkers: meerdere pagina's met hooguit 10 per pagina (14 = 10 + 4), met de
  kopregel op elke pagina en een medewerker nooit over twee pagina's verdeeld.
"""

import os
import re
import threading
from datetime import timedelta

import pytest
from werkzeug.serving import make_server

from app import create_app

from .browser_hulp import NAMEN, WACHTWOORD, BrowserConfig

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
MIGRATIES = os.path.join(os.path.dirname(__file__), "..", "migrations")


def _print_pdf(browser, tmp_path, aantal: int, code: str, zwaar: bool = False):
    """Server met `aantal` medewerkers die deze week elke dag `code` hebben; geeft (pagina's, stijl).

    zwaar: lange namen met een functie en lange dagopmerkingen (hogere kop en naamcellen).
    """
    from flask_migrate import upgrade

    from app.extensions import db
    from app.models import Dagopmerking, Gebruiker, Medewerker
    from app.services import instellingen, klok
    from app.services.voorbeeldpakket import laad_voorbeeldpakket
    from app.services.wachtwoorden import hash_wachtwoord
    from app.services.weekrooster import Wijziging, wijzig_cellen

    app = create_app(BrowserConfig(str(tmp_path)))
    with app.app_context():
        upgrade(directory=MIGRATIES)
        instellingen.schrijf("setup_voltooid", "1")
        laad_voorbeeldpakket()
        maandag = klok.vandaag() - timedelta(days=klok.vandaag().weekday())
        namen = NAMEN + [f"Extra Medewerker {i}" for i in range(30)]
        for i in range(aantal):
            naam = f"{namen[i]} van der Langenaam-Achternaam" if zwaar else namen[i]
            db.session.add(Medewerker(naam=naam, initialen=f"T{i:02d}", volgorde=i,
                                      functie_opmerking="Teamleider beveiliging" if zwaar else ""))
        if zwaar:
            for d in range(7):
                db.session.add(Dagopmerking(datum=maandag + timedelta(days=d),
                                            tekst="Lange dagopmerking over meerdere regels in de kop"))
        db.session.add(Gebruiker(gebruikersnaam="planner", weergavenaam="Planner", rol="beheerder",
                                 wachtwoord_hash=hash_wachtwoord(WACHTWOORD)))
        db.session.commit()
        wijzig_cellen([Wijziging(m.id, maandag + timedelta(days=d), veld, waarde)
                       for m in Medewerker.query.all() for d in range(7)
                       for veld, waarde in (("code", code), ("opmerking", "Later op dienst"))])
        db.session.remove()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    pagina = context.new_page()
    try:
        pagina.goto(url + "/login")
        pagina.fill("input[name=gebruikersnaam]", "planner")
        pagina.fill("input[name=wachtwoord]", WACHTWOORD)
        pagina.click("button[type=submit]")
        pagina.wait_for_url(lambda u: "/login" not in u)
        pagina.goto(url + "/week")
        pagina.emulate_media(media="print")
        pdf = pagina.pdf(prefer_css_page_size=True, print_background=True)
        stijl = pagina.evaluate("""() => ({
            kop: getComputedStyle(document.querySelector('.print-tabel thead')).display,
            perPagina: Array.from(document.querySelectorAll('.print-tabel'), t => t.tBodies.length),
            blok: getComputedStyle(document.querySelector('.print-tabel tbody.p-blok')).breakInside,
            blokken: document.querySelectorAll('.print-tabel tbody.p-blok').length,
            tekst: document.querySelector('.print-rooster').textContent,
        })""")
    finally:
        context.close()
        server.shutdown()
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf)), stijl


@pytest.mark.parametrize("code", ["4", "17/3"])
def test_tien_medewerkers_altijd_op_een_a4(browser, tmp_path, code):
    paginas, stijl = _print_pdf(browser, tmp_path, 10, code)
    assert paginas == 1 and stijl["perPagina"] == [10]
    assert stijl["blokken"] == 10 and "Reserve" not in stijl["tekst"]


def test_dertien_medewerkers_met_twee_diensten_op_een_a4(browser, tmp_path):
    paginas, stijl = _print_pdf(browser, tmp_path, 13, "17/3")
    assert paginas == 1 and stijl["perPagina"] == [13]


@pytest.mark.parametrize("aantal, verdeling", [(14, [10, 4]), (25, [10, 10, 5])])
def test_meer_medewerkers_tien_per_pagina(browser, tmp_path, aantal, verdeling):
    paginas, stijl = _print_pdf(browser, tmp_path, aantal, "17/3")
    assert paginas == len(verdeling) and stijl["perPagina"] == verdeling
    assert stijl["kop"] == "table-header-group"  # kopregel bovenaan elke pagina
    assert stijl["blok"] == "avoid"  # een medewerker nooit over twee pagina's
    assert stijl["blokken"] == aantal and "Reserve" not in stijl["tekst"]


@pytest.mark.parametrize("aantal", [10, 13, 25])
def test_lange_namen_en_dagopmerkingen_lopen_niet_over(browser, tmp_path, aantal):
    """Hogere kop en naamcellen: opgemeten, dus nooit een losse medewerker op een extra pagina."""
    paginas, stijl = _print_pdf(browser, tmp_path, aantal, "17/3", zwaar=True)
    assert paginas == len(stijl["perPagina"]) and sum(stijl["perPagina"]) == aantal
    assert max(stijl["perPagina"]) <= 10
    if aantal == 10:
        assert paginas == 1  # vóór 1.4.4 werden dit er twee
