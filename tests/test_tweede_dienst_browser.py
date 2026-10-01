"""Browsertests (Playwright): twee diensten op één dag (1.4.0).

- '17/3' typen in het code-raster → opslaan → beide diensten onder elkaar in het rooster,
  met eigen uren en het juiste weektotaal; ook na verversen;
- pijltjes slaan de (verborgen) rijen van dienst 2 over bij iemand zonder tweede dienst;
- de printversie toont beide diensten en past op één A4 liggend.
"""

import re

import pytest

from .browser_hulp import nieuwe_pagina

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


def _uren(tekst: str) -> float:
    return float(tekst.replace(",", ".")) if tekst.strip() else 0.0


def _diensten(server, mw_id: int, datum: str) -> dict:
    from datetime import date

    from app.extensions import db
    from app.models import Dienst

    with server.app.app_context():
        resultaat = {d.volgnummer: (d.dienstnaam, d.begin, d.eind, d.uren_berekend) for d in
                     Dienst.query.filter_by(medewerker_id=mw_id, datum=date.fromisoformat(datum))}
        db.session.remove()
        return resultaat


def test_twee_diensten_typen_opslaan_en_tonen(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    # Medewerker op de derde regel, maandag
    cel = pagina.locator(".code-paneel td.code").nth(2 * 7)
    mw, datum = cel.get_attribute("data-mw"), cel.get_attribute("data-datum")
    tweede_rijen = pagina.locator(f'tr[data-tweede="{mw}"]')
    assert tweede_rijen.count() == 0  # nog geen tweede dienst deze week

    cel.click()
    pagina.keyboard.type("17/3")
    pagina.keyboard.press("Enter")
    status = pagina.locator(".code-paneel [data-status]")
    sync_api.expect(status).to_contain_text("niet opgeslagen")
    # Voorbeeld: de rijen van dienst 2 verschijnen al, de code-cel is gesplitst gekleurd
    sync_api.expect(tweede_rijen.first).to_be_visible()
    sync_api.expect(cel).to_have_text("17/3")
    assert "linear-gradient" in cel.get_attribute("style")
    assert _diensten(server, int(mw), datum) != {1: ("BHV", "08:30", "12:30", 4.0),
                                                 2: ("VW Avond", "14:30", "23:00", 8.0)}

    pagina.keyboard.press("Control+s")
    sync_api.expect(status).to_contain_text("Opgeslagen")
    assert _diensten(server, int(mw), datum) == {1: ("BHV", "08:30", "12:30", 4.0),
                                                 2: ("VW Avond", "14:30", "23:00", 8.0)}

    def controleer():
        dag = f'[data-mw="{mw}"][data-datum="{datum}"]'
        naam1 = pagina.locator(f'.rooster {dag}[data-toon="dienstnaam"]:not([data-vn="2"])')
        naam2 = pagina.locator(f'.rooster {dag}[data-toon="dienstnaam"][data-vn="2"]')
        sync_api.expect(naam1).to_have_text("BHV")
        sync_api.expect(naam2).to_have_text("VW Avond")
        # Onder elkaar: dienst 2 staat lager in het rooster dan dienst 1
        assert naam2.bounding_box()["y"] > naam1.bounding_box()["y"]
        assert pagina.locator(f'.rooster {dag}[data-veld="begin"][data-vn="2"]').inner_text() == "14:30"
        assert pagina.locator(f'.rooster {dag}[data-toon="uren"]:not([data-vn="2"])').inner_text() == "4,00"
        assert pagina.locator(f'.rooster {dag}[data-toon="uren"][data-vn="2"]').inner_text() == "8,00"
        # Weektotaal = alle uren van die week, van beide diensten
        alle_uren = pagina.locator(f'.rooster [data-mw="{mw}"][data-toon="uren"]').all_inner_texts()
        totaal = _uren(pagina.locator(f'[data-totaal="{mw}"]').inner_text())
        assert totaal == pytest.approx(sum(_uren(u) for u in alle_uren))
        code = pagina.locator(f'.code-paneel td.code[data-mw="{mw}"][data-datum="{datum}"]')
        assert code.inner_text() == "17/3"

    controleer()
    pagina.reload()
    controleer()

    # Delete in het code-raster wist beide diensten
    cel = pagina.locator(f'.code-paneel td.code[data-mw="{mw}"][data-datum="{datum}"]')
    cel.click()
    pagina.keyboard.press("Delete")
    pagina.keyboard.press("Control+s")
    sync_api.expect(pagina.locator(".code-paneel [data-status]")).to_contain_text("Opgeslagen")
    assert _diensten(server, int(mw), datum) == {}
    context.close()


def test_pijltjes_slaan_verborgen_rijen_over_en_ctrl_z(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    blokken = pagina.locator(".rooster tbody.blok")
    eerste, tweede = blokken.nth(5), blokken.nth(6)
    assert eerste.locator("tr.tweede-rij").count() == 0
    # Van de tijdenregel (rij d) van de ene medewerker naar de opmerking (rij a) van de volgende
    eerste.locator('td[data-veld="begin"]:not([data-vn="2"])').first.click()
    pagina.keyboard.press("ArrowDown")
    actief = pagina.locator(".rooster .cel.actief")
    assert actief.get_attribute("data-veld") == "opmerking"
    assert actief.get_attribute("data-mw") == tweede.get_attribute("data-blok")

    # Tweede dienst erbij via het code-raster, daarna Ctrl+Z: de oude stand komt terug
    mw = eerste.get_attribute("data-blok")
    cel = pagina.locator(f'.code-paneel td.code[data-mw="{mw}"]').nth(1)
    oud = cel.inner_text()
    cel.click()
    pagina.keyboard.type("17/3")
    pagina.keyboard.press("Enter")
    sync_api.expect(cel).to_have_text("17/3")
    sync_api.expect(cel).to_have_class(re.compile("gewijzigd"))  # oranje: nog niet opgeslagen
    sync_api.expect(eerste.locator("tr.tweede-rij").first).to_be_visible()
    # De nieuwe rijen doen mee in het raster: pijltje omlaag vanuit de tijden van dienst 1
    eerste.locator('td[data-veld="begin"]:not([data-vn="2"])').first.click()
    pagina.keyboard.press("ArrowDown")
    assert actief.get_attribute("data-vn") == "2" and actief.get_attribute("data-toon") == "dienstnaam"
    cel.click()
    cel.click()
    pagina.keyboard.press("Control+z")
    sync_api.expect(cel).to_have_text(oud)
    sync_api.expect(pagina.locator("[data-opslaan]")).to_be_disabled()
    context.close()


def test_printversie_met_twee_diensten(server, browser, sessies):
    context, pagina = nieuwe_pagina(browser, "1280x800", sessies["beheerder"])
    pagina.goto(server.url + "/week")
    cel = pagina.locator(".code-paneel td.code").nth(3)
    mw, datum = cel.get_attribute("data-mw"), cel.get_attribute("data-datum")
    cel.click()
    pagina.keyboard.type("17/3")
    pagina.keyboard.press("Control+s")
    sync_api.expect(pagina.locator(".code-paneel [data-status]")).to_contain_text("Opgeslagen")
    pagina.reload()
    pagina.emulate_media(media="print")
    assert pagina.locator(".print-tabel").is_visible()
    assert not pagina.locator(".code-paneel").is_visible() and not pagina.locator(".week-kop").is_visible()
    dag = f'[data-pmw="{mw}"][data-pdatum="{datum}"]'
    assert pagina.locator(f'{dag}[data-pvn="1"][data-p="dienstnaam"]').inner_text() == "BHV"
    assert pagina.locator(f'{dag}[data-pvn="2"][data-p="dienstnaam"]').inner_text() == "VW Avond"
    assert pagina.locator(f'{dag}[data-pvn="2"][data-p="uren"]').inner_text() == "8,00"
    # Dienstcodekleur blijft in de print (balk met de kleur van de code)
    assert "background" in pagina.locator(f'{dag}[data-pvn="2"][data-p="dienstnaam"]').get_attribute("style")
    pdf = pagina.pdf(prefer_css_page_size=True, print_background=True)
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) == 1
    context.close()
