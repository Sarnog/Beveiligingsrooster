"""Browsertest (Playwright): service worker en versiewissel.

Na een nieuwe versie van de app moet de browser het nieuwe script laden en de oude
cache opruimen. Pagina's en API-antwoorden komen nooit uit de cache.
"""

import time

import pytest

import app as app_pakket

from .browser_hulp import nieuwe_pagina

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

CACHE_INHOUD_JS = """async () => {
  const uit = {};
  for (const naam of await caches.keys()) {
    const cache = await caches.open(naam);
    uit[naam] = (await cache.keys()).map(r => new URL(r.url).pathname + new URL(r.url).search);
  }
  return uit;
}"""


def _wacht_op(pagina, js: str, verwacht, seconden: float = 10):
    """Herhaal een controle in de pagina tot de uitkomst klopt (wait_for_function mag niet door de CSP)."""
    einde = time.time() + seconden
    while True:
        uitkomst = pagina.evaluate(js)
        if verwacht(uitkomst) or time.time() > einde:
            return uitkomst
        time.sleep(0.2)


def test_service_worker_versiewissel_laadt_nieuw_script(server, browser, sessies, monkeypatch):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.goto(server.url + "/kalender/")
    assert pagina.evaluate("navigator.serviceWorker.ready.then(r => r.active.scriptURL)").endswith("/sw.js")
    oud = app_pakket.VERSIE
    caches = _wacht_op(pagina, CACHE_INHOUD_JS, lambda c: f"rooster-{oud}" in c and c[f"rooster-{oud}"])
    assert list(caches) == [f"rooster-{oud}"]
    # Alleen statische bestanden met versie en de offline-pagina; nooit HTML of /api/
    for adres in caches[f"rooster-{oud}"]:
        assert adres.startswith("/static/") and f"v={oud}" in adres or adres == f"/offline?v={oud}", adres

    # Nieuwe versie van de app uitgebracht
    monkeypatch.setattr(app_pakket, "VERSIE", "9.9.9")
    geladen = []
    pagina.on("response", lambda r: geladen.append((r.url, r.status, r.from_service_worker)))
    pagina.reload()
    assert any("js/app.js?v=9.9.9" in url and status == 200 for url, status, _sw in geladen)
    assert not any("v=" + oud in url for url, _s, _sw in geladen if "/static/" in url)
    # De nieuwe service worker neemt het over en ruimt de oude cache op
    caches = _wacht_op(pagina, CACHE_INHOUD_JS, lambda c: list(c) == ["rooster-9.9.9"])
    assert list(caches) == ["rooster-9.9.9"], caches

    # Tweede keer laden: het script komt nu uit de cache van de nieuwe versie
    geladen.clear()
    pagina.reload()
    assert any("js/app.js?v=9.9.9" in url and sw for url, _s, sw in geladen)
    context.close()


def test_offline_toont_melding_en_geen_oude_pagina(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.goto(server.url + "/mijn")
    pagina.evaluate("navigator.serviceWorker.ready.then(() => true)")
    _wacht_op(pagina, "navigator.serviceWorker.controller !== null", bool)
    if not pagina.evaluate("navigator.serviceWorker.controller !== null"):
        pagina.reload()  # de eerste pagina wordt pas na een herlaadbeurt door de worker bediend
    context.set_offline(True)
    pagina.goto(server.url + "/mijn")
    assert "Je bent offline" in pagina.content()
    assert "Mijn rooster" not in pagina.locator("main").inner_text()  # geen bewaarde pagina
    context.set_offline(False)
    pagina.goto(server.url + "/mijn")
    assert "Mijn rooster" in pagina.locator("main").inner_text()
    context.close()


def test_manifest_installeerbaar(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "412x915", sessies["collega"])
    pagina.goto(server.url + "/mijn")
    manifest = pagina.evaluate("""async () => {
        const link = document.querySelector('link[rel=manifest]');
        const antwoord = await fetch(link.href);
        return antwoord.json();
    }""")
    assert manifest["display"] == "standalone"
    for icoon in manifest["icons"]:
        antwoord = pagina.request.get(server.url + icoon["src"])
        assert antwoord.ok and antwoord.headers["content-type"] == "image/png"
    context.close()
