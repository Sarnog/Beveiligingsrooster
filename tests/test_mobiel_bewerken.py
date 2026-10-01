"""Browsertests (Playwright): weekrooster op de telefoon bekijken en wijzigen.

- dagweergave en medewerkerweergave, knoppen en vegen;
- wisselen tussen raster en telefoonweergave (onthouden in localStorage);
- bewerkpaneel: dag aantikken, code kiezen, opslaan → database; conflict (409) → melding;
- het Excel-achtige raster op de desktop werkt nog zoals voorheen;
- printen vanaf een telefoon: A4 liggend op één pagina.
"""

import re

import pytest

from .browser_hulp import WACHTWOORD, nieuwe_pagina

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


def _dienst(server, mw_id: int, datum: str):
    from datetime import date

    from app.extensions import db
    from app.models import Dienst

    with server.app.app_context():
        dienst = Dienst.query.filter_by(medewerker_id=mw_id, datum=date.fromisoformat(datum)).first()
        gegevens = None if dienst is None else {
            "code": dienst.dienstcode.nummer if dienst.dienstcode else None, "begin": dienst.begin,
            "eind": dienst.eind, "versie": dienst.versie, "uren": dienst.uren_berekend,
            "opmerking": dienst.opmerking_tekst, "tijden_handmatig": dienst.tijden_handmatig}
        db.session.remove()
        return gegevens


def _zichtbare_dag(pagina) -> str:
    return pagina.locator("[data-dagpagina]:visible h2").inner_text()


def test_dagweergave_vorige_volgende_en_vegen(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.goto(server.url + "/week")
    assert pagina.locator(".week-mobiel").is_visible() and not pagina.locator(".rooster").is_visible()
    # Begint op vandaag; één dag tegelijk, met alle medewerkers
    assert "vandaag" in _zichtbare_dag(pagina)
    assert pagina.locator("[data-dagpagina]:visible .dag-kaart").count() == 15
    start = pagina.locator("[data-mobiel-paneel=dag] [data-mobiel-kies]").input_value()

    pagina.click("[data-mobiel-paneel=dag] [data-mobiel-volgende]")
    eerste_stap = pagina.locator("[data-mobiel-paneel=dag] [data-mobiel-kies]").input_value()
    if start != "6":  # op zondag gaat 'volgende' naar de volgende week
        assert int(eerste_stap) == int(start) + 1
        # Vegen naar rechts = vorige dag
        pagina.evaluate("""() => {
            const el = document.querySelector('[data-week-mobiel]');
            const t = (x) => new Touch({identifier: 1, target: el, clientX: x, clientY: 300});
            el.dispatchEvent(new TouchEvent('touchstart', {touches: [t(50)], bubbles: true}));
            el.dispatchEvent(new TouchEvent('touchend', {changedTouches: [t(250)], bubbles: true}));
        }""")
        assert pagina.locator("[data-mobiel-paneel=dag] [data-mobiel-kies]").input_value() == start
    context.close()


def test_medewerkerweergave_zeven_dagen_en_onthouden(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.goto(server.url + "/week")
    pagina.click("[data-mobiel-modus=medewerker]")
    assert pagina.locator("[data-mwpagina]:visible").count() == 1
    assert pagina.locator("[data-mwpagina]:visible .dag-kaart").count() == 7
    # De collega begint bij zichzelf (gekoppelde medewerker)
    assert "Anna de Vries-van Bergen" in pagina.locator("[data-mwpagina]:visible h2").inner_text()
    pagina.click("[data-mobiel-paneel=medewerker] [data-mobiel-volgende]")
    assert "Bram Jansen" in pagina.locator("[data-mwpagina]:visible h2").inner_text()
    pagina.reload()
    assert pagina.locator("[data-mobiel-paneel=medewerker]").is_visible()  # keuze onthouden
    context.close()


def test_wisselen_tussen_raster_en_telefoonweergave(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "768x1024", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    assert pagina.locator(".rooster").is_visible() and not pagina.locator(".week-mobiel").is_visible()
    pagina.click("[data-weergave-wissel]")
    assert pagina.locator(".week-mobiel").is_visible() and not pagina.locator(".rooster").is_visible()
    assert pagina.locator("[data-weergave-wissel]").inner_text() == "Rasterweergave"
    pagina.reload()
    assert pagina.locator(".week-mobiel").is_visible()  # per gebruiker onthouden
    pagina.click("[data-weergave-wissel]")
    assert pagina.locator(".rooster").is_visible()
    context.close()


def test_weergave_zonder_localstorage_werkt_gewoon(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.add_init_script("Object.defineProperty(window, 'localStorage', "
                           "{get() { throw new Error('geblokkeerd'); }});")
    fouten = []
    pagina.on("pageerror", lambda fout: fouten.append(str(fout)))
    pagina.goto(server.url + "/week")
    pagina.click("[data-mobiel-modus=medewerker]")
    assert pagina.locator("[data-mwpagina]:visible").count() == 1
    assert not fouten
    context.close()


def _open_paneel(pagina, mw_id: int):
    kaart = pagina.locator(f"[data-dagpagina]:visible [data-bewerk-dag][data-mw='{mw_id}']")
    datum = kaart.get_attribute("data-datum")
    kaart.click()
    assert pagina.locator("#dienst-paneel").is_visible()
    return kaart, datum


def test_planner_wijzigt_dienst_op_telefoon(server, browser, sessies):
    mw_id = server.gegevens["medewerkers"][2]
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    kaart, datum = _open_paneel(pagina, mw_id)
    oud = _dienst(server, mw_id, datum)
    # Velden zijn ingevuld met de huidige dienst
    if oud and oud["code"]:
        assert pagina.locator("#dienst-paneel select[name=code]").input_value() == str(oud["code"])
    # Paneel past op het scherm en de velden zijn groot genoeg
    vak = pagina.locator("#dienst-paneel").bounding_box()
    assert vak["x"] >= 0 and vak["x"] + vak["width"] <= 390

    pagina.select_option("#dienst-paneel select[name=code]", "13")  # Cursus 07:15–15:45
    expect = sync_api.expect
    expect(pagina.locator("#dienst-paneel input[name=begin]")).to_have_value("07:15")
    expect(pagina.locator("#dienst-paneel input[name=eind]")).to_have_value("15:45")
    expect(pagina.locator("[data-paneel-uren]")).to_have_text(re.compile(r"\d"))
    pagina.fill("#dienst-paneel input[name=opmerking]", "Locatie B")
    pagina.click("[data-paneel-opslaan]")
    expect(pagina.locator("#dienst-paneel")).to_be_hidden()

    nieuw = _dienst(server, mw_id, datum)
    assert nieuw["code"] == 13 and nieuw["opmerking"] == "Locatie B"
    assert (nieuw["begin"], nieuw["eind"]) == ("07:15", "15:45")
    assert not nieuw["tijden_handmatig"]  # standaardtijden, geen eigen tijden
    assert "Cursus" in kaart.inner_text() and "Locatie B" in kaart.inner_text()
    assert pagina.locator("[data-opslaan]").first.is_disabled()  # niets meer te bewaren

    # Eigen tijd invullen: wordt als handmatige tijd opgeslagen
    _open_paneel(pagina, mw_id)
    pagina.fill("#dienst-paneel input[name=eind]", "17:00")
    pagina.click("[data-paneel-opslaan]")
    expect(pagina.locator("#dienst-paneel")).to_be_hidden()
    nieuw = _dienst(server, mw_id, datum)
    assert nieuw["eind"] == "17:00" and nieuw["tijden_handmatig"] and nieuw["code"] == 13
    context.close()


def test_conflict_verouderde_versie(server, browser, sessies):
    """Iemand anders wijzigde de dienst nadat de pagina geladen is: niets overschrijven."""
    from datetime import date

    from app.extensions import db
    from app.models import Dienst

    mw_id = server.gegevens["medewerkers"][3]
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    _kaart, datum = _open_paneel(pagina, mw_id)
    with server.app.app_context():
        dienst = Dienst.query.filter_by(medewerker_id=mw_id, datum=date.fromisoformat(datum)).first()
        if dienst is None:
            dienst = Dienst(medewerker_id=mw_id, datum=date.fromisoformat(datum))
            db.session.add(dienst)
        dienst.opmerking_tekst = "Door een ander"
        dienst.versie = (dienst.versie or 1) + 1
        db.session.commit()
        db.session.remove()

    pagina.select_option("#dienst-paneel select[name=code]", "12")
    pagina.click("[data-paneel-opslaan]")
    sync_api.expect(pagina.locator("#dienst-paneel [data-status]")).to_contain_text(
        "net door iemand anders gewijzigd")
    assert pagina.locator("#dienst-paneel").is_visible()
    na = _dienst(server, mw_id, datum)
    assert na["opmerking"] == "Door een ander" and na["code"] != 12
    # De nieuwste stand staat nu in de kaart
    assert "Door een ander" in pagina.locator(
        f"[data-dagpagina]:visible [data-bewerk-dag][data-mw='{mw_id}']").inner_text()
    # Zoals in het raster: de conflicterende wijziging vervalt, er staat niets meer klaar
    pagina.locator("[data-paneel-annuleren]").click()
    assert pagina.locator("[data-opslaan]").first.is_disabled()
    context.close()


def test_conflict_409_tijdens_opslaan(server, browser, sessies):
    """Twee planners slaan exact tegelijk op: de server antwoordt 409."""
    mw_id = server.gegevens["medewerkers"][5]
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    verzoeken = []

    def onderschep(route):
        gegevens = route.request.post_data_json
        verzoeken.append({"opslaan": gegevens["opslaan"], "csrf": route.request.headers.get("x-csrftoken")})
        if gegevens["opslaan"] is True:
            route.fulfill(status=409, content_type="application/json",
                          body='{"fout": "Iemand anders wijzigde tegelijk dezelfde dienst."}')
        else:
            route.continue_()

    pagina.route("**/api/cellen", onderschep)
    _kaart, datum = _open_paneel(pagina, mw_id)
    voor = _dienst(server, mw_id, datum)
    pagina.select_option("#dienst-paneel select[name=code]", "14")
    pagina.click("[data-paneel-opslaan]")
    sync_api.expect(pagina.locator("#dienst-paneel [data-status]")).to_contain_text(
        "Iemand anders wijzigde tegelijk dezelfde dienst. Niets opgeslagen")
    assert pagina.locator("#dienst-paneel").is_visible()
    assert _dienst(server, mw_id, datum) == voor
    assert any(v["opslaan"] is True for v in verzoeken)
    assert all(v["csrf"] for v in verzoeken)  # CSRF-header altijd mee
    # De wijziging staat nog klaar: wie weggaat, krijgt eerst de vraag
    pagina.locator("[data-paneel-annuleren]").click()
    sync_api.expect(pagina.locator("[data-opslaan]").first).to_have_text("Opslaan (1)")
    pagina.click("a.merk")
    assert pagina.locator("#niet-opgeslagen").is_visible()
    context.close()


def test_desktop_raster_toetsenbord_ongewijzigd(server, browser, sessies):
    mw_id = server.gegevens["medewerkers"][4]
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    assert pagina.locator(".rooster").is_visible() and not pagina.locator(".week-mobiel").is_visible()
    assert not pagina.locator("[data-weergave-wissel]").is_visible()
    cel = pagina.locator(f".code-paneel .cel[data-mw='{mw_id}']").first
    datum = cel.get_attribute("data-datum")
    cel.click()
    pagina.keyboard.type("16")
    pagina.keyboard.press("Enter")
    sync_api.expect(pagina.locator("[data-opslaan]").first).to_have_text("Opslaan (1)")
    pagina.keyboard.press("Control+s")
    sync_api.expect(pagina.locator(".code-paneel [data-status]")).to_contain_text("Opgeslagen")
    assert _dienst(server, mw_id, datum)["code"] == 16
    context.close()


def test_printen_vanaf_telefoon_een_a4_liggend(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "390x844", sessies["collega"])
    pagina.goto(server.url + "/week")
    pagina.emulate_media(media="print")
    # Bij printen: de printtabel (papieren rooster), niet het schermrooster of de telefoonweergave
    assert pagina.locator(".print-tabel").is_visible()
    assert not pagina.locator(".rooster").is_visible()
    assert not pagina.locator(".week-mobiel").is_visible()
    pdf = pagina.pdf(prefer_css_page_size=True, print_background=True)
    pagina_aantal = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    assert pagina_aantal == 1, f"{pagina_aantal} pagina's"
    breedte, hoogte = (float(x) for x in re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)", pdf).groups())
    assert breedte > hoogte  # liggend
    assert abs(breedte - 842) < 2 and abs(hoogte - 595) < 2  # A4
    context.close()


def test_inloggen_op_telefoon(server, browser):
    context, pagina = nieuwe_pagina(browser, "360x640")
    pagina.goto(server.url + "/login")
    pagina.fill("input[name=gebruikersnaam]", "collega")
    pagina.fill("input[name=wachtwoord]", WACHTWOORD)
    pagina.click("button[type=submit]")
    pagina.wait_for_url("**/mijn")
    assert pagina.locator("[data-blok=vandaag]").is_visible()
    assert pagina.locator("[data-agenda-knop]").bounding_box()["height"] >= 44
    context.close()
