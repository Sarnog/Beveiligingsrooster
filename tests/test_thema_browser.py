"""Schakelaar licht/donker in een echte browser: wisselt het thema en onthoudt de keuze."""

import pytest

from .browser_hulp import nieuwe_pagina

pytest.importorskip("playwright.sync_api")


def _achtergrond(pagina) -> str:
    return pagina.evaluate("getComputedStyle(document.body).backgroundColor")


@pytest.mark.parametrize("apparaat", ["light", "dark"])
def test_schakelaar_wisselt_tegenover_het_apparaat(server, browser, sessies, apparaat):
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["collega"])
    try:
        pagina.emulate_media(color_scheme=apparaat)
        pagina.goto(server.url + "/account/tokens")
        voor = _achtergrond(pagina)
        # Eerdere keuze (uit een vorige test) gaat voor; anders telt het apparaat
        huidig = pagina.get_attribute("html", "data-thema") or ("donker" if apparaat == "dark" else "licht")
        verwacht = "licht" if huidig == "donker" else "donker"

        pagina.click(".thema-schakelaar")
        pagina.wait_for_load_state()
        assert pagina.get_attribute("html", "data-thema") == verwacht
        assert _achtergrond(pagina) != voor
        assert pagina.url.endswith("/account/tokens")

        # Nog een keer: terug naar hetzelfde thema als het apparaat
        pagina.click(".thema-schakelaar")
        pagina.wait_for_load_state()
        assert _achtergrond(pagina) == voor
    finally:
        context.close()
