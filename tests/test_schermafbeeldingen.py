"""Schermafbeeldingen van de belangrijkste schermen (390×844 en 1280×800).

Alleen als SCHERMAFBEELDINGEN een map noemt, bijvoorbeeld:
    SCHERMAFBEELDINGEN=docs/schermafbeeldingen pytest -q tests/test_schermafbeeldingen.py
"""

import os
import re

import pytest

from .browser_hulp import nieuwe_pagina

pytest.importorskip("playwright.sync_api")
pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not os.environ.get("SCHERMAFBEELDINGEN"), reason="SCHERMAFBEELDINGEN niet gezet"),
]

SCHERMEN = [
    # (bestandsnaam, rol, pad, voorbereiding)
    ("inloggen", None, "/login", None),
    ("mijn-rooster", "collega", "/mijn", None),
    ("week-per-dag", "collega", "/week", None),
    ("week-per-medewerker", "collega", "/week", "medewerker"),
    ("week-planner", "beheerder", "/week", None),
    ("week-planner-dienst-wijzigen", "beheerder", "/week", "paneel"),
    ("menu", "beheerder", "/kalender/", "menu"),
    ("kalender", "collega", "/kalender/", None),
    ("urenoverzicht", "beheerder", "/overzicht/uren", None),
    ("beheer", "beheerder", "/beheer/", None),
    ("logboek", "beheerder", "/beheer/logboek", None),
]


@pytest.mark.parametrize("scherm", ["390x844", "1280x800"])
def test_schermafbeeldingen(server, browser, sessies, scherm):
    map_ = os.environ["SCHERMAFBEELDINGEN"]
    os.makedirs(map_, exist_ok=True)
    telefoon = scherm == "390x844"
    for naam, rol, pad, voorbereiding in SCHERMEN:
        if not telefoon and voorbereiding in ("medewerker", "paneel", "menu"):
            continue  # alleen op de telefoon
        context, pagina = nieuwe_pagina(browser, scherm, sessies[rol] if rol else None)
        pagina.goto(server.url + pad)
        if voorbereiding == "medewerker":
            pagina.click("[data-mobiel-modus=medewerker]")
        elif voorbereiding == "paneel":
            pagina.locator("[data-dagpagina]:visible [data-bewerk-dag]").nth(2).click()
            pagina.select_option("#dienst-paneel select[name=code]", "13")
            pagina.locator("[data-paneel-uren]").filter(has_text=re.compile(r"\d")).wait_for()
        elif voorbereiding == "menu":
            pagina.click(".menu-knop")
        pagina.screenshot(path=os.path.join(map_, f"{naam}-{scherm}.png"),
                          full_page=not telefoon)  # telefoon: één scherm, zoals je het ziet
        context.close()
