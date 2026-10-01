"""Browsertest (Playwright): roosterpatroon maken, droogloop bekijken en toepassen (1.6.0).

Het patroon wordt uitgerold in een jaar ver vooruit, zodat de andere browsertests (die het
huidige en het volgende jaar gebruiken) er niets van merken.
"""

from datetime import date

import pytest

from .browser_hulp import NAMEN, nieuwe_pagina

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


def _codes(server, naam: str, jaar: int) -> dict:
    from app.extensions import db
    from app.models import Dienst, Medewerker

    with server.app.app_context():
        medewerker = Medewerker.query.filter_by(naam=naam).one()
        resultaat = {(d.datum, d.volgnummer): d.dienstcode.nummer for d in Dienst.query.filter(
            Dienst.medewerker_id == medewerker.id, Dienst.datum >= date(jaar, 1, 1),
            Dienst.datum <= date(jaar, 12, 31)) if d.dienstcode}
        db.session.remove()
        return resultaat


def test_patroon_maken_droogloop_en_toepassen(server, browser, sessies):
    from app.services import klok

    jaar = klok.vandaag().year + 2
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["beheerder"])
    pagina.goto(server.url + "/beheer/patronen")
    pagina.click("text=Nieuw patroon")
    pagina.fill("input[name=naam]", "Browserpatroon")
    pagina.fill("input[name=weken]", "2")
    pagina.click("button[name=actie][value=weken]")
    sync_api.expect(pagina.locator("[data-patroon-raster] tbody tr")).to_have_count(2)
    pagina.fill("input[name=c-1-0]", "4")
    pagina.fill("input[name=c-1-1]", "4/7")
    pagina.fill("input[name=c-2-0]", "99")  # bestaat niet: melding
    pagina.click("button[name=actie][value=opslaan]")
    sync_api.expect(pagina.locator(".melding").first).to_contain_text("Onbekende dienstcode: 99")
    pagina.fill("input[name=c-2-0]", "7")
    pagina.click("button[name=actie][value=opslaan]")
    sync_api.expect(pagina.locator("[data-patronen]")).to_contain_text("Browserpatroon")

    # Uitrollen: twee medewerkers, de tweede begint in week 2 van de cyclus
    pagina.click("[data-patronen] >> text=Uitrollen…")
    eerste, tweede = (pagina.locator(f"label.vink:has-text('{naam}')") for naam in NAMEN[:2])
    eerste.locator("input").check()
    tweede.locator("input").check()
    rij_tweede = pagina.locator(".keuze-medewerkers .rij").nth(1)
    rij_tweede.locator("input[type=number]").fill("2")
    pagina.fill("input[name=van]", f"{jaar}-W10")
    pagina.fill("input[name=tot_week]", f"{jaar}-W11")
    pagina.click("button[name=actie][value=voorbeeld]")
    tabel = pagina.locator("table[data-effect]")
    sync_api.expect(tabel).to_contain_text(NAMEN[0])
    sync_api.expect(pagina.locator("[data-totaal-effect]")).to_contain_text("Totaal: 8 nieuw, 0 vervangen")
    assert _codes(server, NAMEN[0], jaar) == {}  # droogloop: nog niets gewijzigd

    pagina.check("input[name=bevestig]")
    pagina.click("button[name=actie][value=toepassen]")
    pagina.wait_for_url(lambda url: f"/week/{jaar}/10" in url)
    sync_api.expect(pagina.locator("body")).to_contain_text("Browserpatroon' toegepast")
    maandag = date.fromisocalendar(jaar, 10, 1)
    volgende = date.fromisocalendar(jaar, 11, 1)
    assert _codes(server, NAMEN[0], jaar)[(maandag, 1)] == 4
    assert _codes(server, NAMEN[0], jaar)[(volgende, 1)] == 7
    assert _codes(server, NAMEN[1], jaar)[(maandag, 1)] == 7  # startpositie 2
    context.close()
