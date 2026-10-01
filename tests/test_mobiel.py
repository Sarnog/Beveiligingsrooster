"""Browsertests (Playwright): elke pagina op elk doelscherm, plus het menu.

Per pagina × scherm:
- geen horizontaal scrollen van de pagina (scrollWidth <= breedte);
- geen elementen buiten beeld (behalve in een bewust scrollbare tabel, met hint);
- op telefoon/tablet: invoervelden minimaal 16 px, menuknoppen en -links minimaal 44 × 44 px;
- het menu (hamburger) opent en sluit, ook met het toetsenbord.

Draait alleen als Playwright en Chromium beschikbaar zijn; anders overgeslagen
(met BROWSERTESTS=verplicht faalt de test dan juist). Zie README → Ontwikkelen.
"""


import pytest

from .browser_hulp import SCHERMEN, nieuwe_pagina

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

# Pagina's per rol (de beheerder ziet ook alle beheerschermen)
PAGINAS_COLLEGA = [
    "/kalender/", "/week", "/mijn", "/mijn/agenda", "/overzicht/uren",
    "/zoeken/?naam=Anna", "/account/wachtwoord", "/account/tokens",
]
PAGINAS_BEHEERDER = [
    "/week", "/kalender/", "/overzicht/uren", "/zoeken/?code=4", "/beheer/",
    "/beheer/medewerkers", "/beheer/medewerkers/nieuw", "/beheer/medewerkers/1",
    "/beheer/dienstcodes", "/beheer/dienstcodes/nieuw", "/beheer/dienstcodes/4",
    "/beheer/gebruikers", "/beheer/gebruikers/nieuw", "/beheer/instellingen",
    "/beheer/vakanties", "/beheer/feestdagen", "/beheer/logboek", "/beheer/backups",
    "/beheer/agenda", "/beheer/importeren", "/beheer/debuglog", "/beheer/herberekenen",
    "/beheer/statistieken",
]

# Controle in de pagina: wat steekt er buiten beeld?
CONTROLE_JS = """
(breedte) => {
  const schuift = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (['auto', 'scroll', 'hidden'].includes(s.overflowX)) return p;
    }
    return null;
  };
  const naam = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.className && typeof el.className === 'string'
      ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
  const buiten = [];
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    if (el.closest('dialog:not([open])')) continue;
    if ((r.right > breedte + 1 || r.left < -1) && !schuift(el)) {
      buiten.push(naam(el) + ' [' + Math.round(r.left) + '..' + Math.round(r.right) + ']');
    }
  }
  // Scrollbare tabellen: moeten een zichtbare hint hebben
  const zonderHint = [];
  for (const houder of document.querySelectorAll('.tabel-schuif')) {
    if (!houder.offsetParent || houder.scrollWidth <= houder.clientWidth + 1) continue;
    const hint = houder.previousElementSibling;
    if (!hint || !hint.classList.contains('schuif-hint') || !hint.offsetParent) zonderHint.push(naam(houder));
  }
  const kleineVelden = [];
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (!el.offsetParent || ['hidden', 'checkbox', 'radio', 'color', 'file'].includes(el.type)) continue;
    if (parseFloat(getComputedStyle(el).fontSize) < 16) {
      kleineVelden.push(naam(el) + '[' + (el.name || '') + ']');
    }
  }
  return {scrollBreedte: document.documentElement.scrollWidth, binnenBreedte: innerWidth,
          buiten: buiten.slice(0, 8), zonderHint, kleineVelden: kleineVelden.slice(0, 8)};
}
"""


def controleer(pagina, scherm: str) -> None:
    breedte, _hoogte, mobiel = SCHERMEN[scherm]
    uitkomst = pagina.evaluate(CONTROLE_JS, breedte)
    assert uitkomst["scrollBreedte"] <= breedte, f"pagina scrolt horizontaal: {uitkomst}"
    assert uitkomst["binnenBreedte"] <= breedte, f"pagina is uitgezoomd: {uitkomst}"
    assert not uitkomst["buiten"], f"elementen buiten beeld: {uitkomst['buiten']}"
    if mobiel:
        assert not uitkomst["zonderHint"], f"scrollbare tabel zonder hint: {uitkomst['zonderHint']}"
        assert not uitkomst["kleineVelden"], f"invoervelden kleiner dan 16 px: {uitkomst['kleineVelden']}"


def controleer_menu(pagina, scherm: str) -> None:
    """Hamburgermenu: zichtbaar op smalle/aanraakschermen, tikdoelen >= 44 px, open en dicht."""
    knop = pagina.locator(".menu-knop")
    if not knop.is_visible():
        assert SCHERMEN[scherm][0] > 1024, "geen menuknop op een smal scherm"
        assert pagina.locator("#hoofdmenu").is_visible()
        return
    vak = knop.bounding_box()
    assert vak["width"] >= 44 and vak["height"] >= 44, f"menuknop te klein: {vak}"
    assert knop.get_attribute("aria-expanded") == "false"
    assert knop.get_attribute("aria-controls") == "hoofdmenu"
    assert not pagina.locator("#hoofdmenu").is_visible()

    knop.click()
    assert knop.get_attribute("aria-expanded") == "true"
    assert pagina.locator("#hoofdmenu").is_visible()
    for doel in pagina.locator("#hoofdmenu a, #hoofdmenu button").all():
        vak = doel.bounding_box()
        assert vak["height"] >= 44 and vak["width"] >= 44, f"tikdoel te klein: {doel.inner_text()} {vak}"
    # Menu opengeklapt: nog steeds niets buiten beeld
    controleer(pagina, scherm)

    knop.click()
    assert knop.get_attribute("aria-expanded") == "false"
    assert not pagina.locator("#hoofdmenu").is_visible()

    # Toetsenbord: Enter opent, focus naar het eerste menu-item, Escape sluit en focus terug
    knop.focus()
    pagina.keyboard.press("Enter")
    assert pagina.locator("#hoofdmenu").is_visible()
    assert pagina.evaluate("document.activeElement.closest('#hoofdmenu') !== null")
    pagina.keyboard.press("Escape")
    assert not pagina.locator("#hoofdmenu").is_visible()
    assert pagina.evaluate("document.activeElement.classList.contains('menu-knop')")


@pytest.mark.parametrize("scherm", list(SCHERMEN))
def test_inlogpagina(server, browser, scherm):
    context, pagina = nieuwe_pagina(browser, scherm)
    pagina.goto(server.url + "/login")
    controleer(pagina, scherm)
    context.close()


@pytest.mark.parametrize("scherm", list(SCHERMEN))
@pytest.mark.parametrize("pad", PAGINAS_COLLEGA)
def test_pagina_collega(server, browser, sessies, scherm, pad):
    context, pagina = nieuwe_pagina(browser, scherm, sessies["collega"])
    antwoord = pagina.goto(server.url + pad)
    assert antwoord.status == 200
    controleer(pagina, scherm)
    if pad == "/kalender/":
        controleer_menu(pagina, scherm)
    context.close()


@pytest.mark.parametrize("scherm", list(SCHERMEN))
@pytest.mark.parametrize("pad", PAGINAS_BEHEERDER)
def test_pagina_beheerder(server, browser, sessies, scherm, pad):
    context, pagina = nieuwe_pagina(browser, scherm, sessies["beheerder"])
    antwoord = pagina.goto(server.url + pad)
    assert antwoord.status == 200
    controleer(pagina, scherm)
    if pad == "/beheer/":
        controleer_menu(pagina, scherm)
    context.close()
