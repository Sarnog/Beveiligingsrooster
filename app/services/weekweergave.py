"""HTML van de dagcellen in het weekrooster en van de telefoonkaarten (snelheid).

Een week met 15 medewerkers heeft 15 x 7 x 8 cellen in het rooster en 2 x 105 kaarten in de
telefoonweergave. In Jinja kostte dat het grootste deel van de laadtijd van de pagina; hier
worden ze met gewone Python-tekst opgebouwd, wat vele malen sneller is. Alle tekst wordt
ge-escaped (markupsafe.escape), net als in een template.

De opbouw van de cellen staat beschreven in week.html (vaste plekken a, b1-b3, c, d1-d3).
raster.js (vulDag) zet dezelfde indeling in de browser na een wijziging.
"""

from markupsafe import Markup, escape


def _opmerking_tekst(d: dict) -> str:
    """Opmerking met de opmerkingtijden erachter, bijv. 'Later op dienst (09:30–18:00)'."""
    if d["opm_begin"] or d["opm_eind"]:
        return f"{d['opmerking']} ({d['opm_begin']}–{d['opm_eind']})"
    return d["opmerking"]


def _tijden(k: str, plek: str, mw: int, datum: str, vn: str, r: int, c0: int, o: dict) -> str:
    """Begin, eind en uren van één dienst (drie cellen op één regel)."""
    h, ht = (" handmatig", ' title="Handmatig aangepast"') if o["handmatig"] else ("", "")
    u, ut = (" handmatig", ' title="Zelf ingevulde uren"') if o["uren_handmatig"] else ("", "")
    basis = f'data-mw="{mw}" data-datum="{datum}"{vn}'
    return (
        f'<td class="{k}tijd{h}" data-plek="{plek}1" {basis} data-veld="begin" data-r="{r}" '
        f'data-c="{c0}"{ht}>{escape(o["begin"])}</td>'
        f'<td class="{k}tijd{h}" data-plek="{plek}2" {basis} data-veld="eind" data-r="{r}" '
        f'data-c="{c0 + 1}"{ht}>{escape(o["eind"])}</td>'
        f'<td class="{k}uren{u}" data-plek="{plek}3" {basis} data-toon="uren" data-veld="uren" '
        f'data-r="{r}" data-c="{c0 + 2}"{ut}>{escape(o["uren"])}</td>'
    )


def _dienstnaam(k: str, plek: str, mw: int, datum: str, vn: str, r: int, c0: int, o: dict,
                extra: str = "") -> str:
    return (f'<td colspan="3" class="{k}dienstnaam" data-plek="{plek}" data-mw="{mw}" '
            f'data-datum="{datum}"{vn} data-toon="dienstnaam" data-veld="dienstnaam" data-r="{r}" '
            f'data-c="{c0}" data-cs="3" data-versie="{o["versie"]}"{extra} '
            f'style="{escape(o["dienst_stijl"])}">{escape(o["dienstnaam"])}</td>')


def blok_regels(rij, dag_iso: list[str], r: int, bewerken: bool) -> list[Markup]:
    """De dagcellen van de vier regels (a-d) van één medewerkerblok, als HTML.

    Eén dienst (of geen): a opmerking, b opmerkingtijden, c dienstnaam, d begin/eind/uren.
    Twee diensten: a/b dienst 1 (opmerking achter de dienstnaam, data-opm), c/d dienst 2.
    r is het rijnummer van het blok in het raster (data-r), bewerken = beheerder.
    """
    k = "cel " if bewerken else ""
    mw = rij.medewerker.id
    regels: list[list[str]] = [[], [], [], []]
    for i, d in enumerate(rij.dagen):
        datum, c0, t = dag_iso[i], i * 3, d["tweede"]
        if t:
            opm = escape(_opmerking_tekst(d))
            extra = f' data-opm="{opm}" title="Opmerking: {opm}"' if opm else ""
            regels[0].append(_dienstnaam(k, "a", mw, datum, "", r + 1, c0, d, extra))
            regels[1].append(_tijden(k, "b", mw, datum, "", r + 2, c0, d))
        else:
            regels[0].append(
                f'<td colspan="3" class="{k}opm" data-plek="a" data-mw="{mw}" data-datum="{datum}" '
                f'data-veld="opmerking" data-r="{r + 1}" data-c="{c0}" data-cs="3" '
                f'style="{escape(d["opmerking_stijl"])}">{escape(d["opmerking"])}</td>')
            regels[1].append(
                f'<td class="{k}tijd opmtijd" data-plek="b1" data-mw="{mw}" data-datum="{datum}" '
                f'data-veld="opm_begin" data-r="{r + 2}" data-c="{c0}">{escape(d["opm_begin"])}</td>'
                f'<td class="{k}tijd opmtijd" data-plek="b2" data-mw="{mw}" data-datum="{datum}" '
                f'data-veld="opm_eind" data-r="{r + 2}" data-c="{c0 + 1}">{escape(d["opm_eind"])}</td>'
                f'<td class="leeg" data-plek="b3" data-mw="{mw}" data-datum="{datum}" '
                f'data-r="{r + 2}" data-c="{c0 + 2}"></td>')
        o, vn = (t, ' data-vn="2"') if t else (d, "")
        regels[2].append(_dienstnaam(k, "c", mw, datum, vn, r + 3, c0, o))
        regels[3].append(_tijden(k, "d", mw, datum, vn, r + 4, c0, o))
    return [Markup("".join(regel)) for regel in regels]


def kaart(mw_id: int, datum: str, d: dict, titel: str, bewerken: bool) -> Markup:
    """Eén dagkaart in de telefoonweergave (de beheerder tikt erop om te wijzigen)."""
    titel = escape(titel)
    if bewerken:
        open_ = (f'<button type="button" class="dag-kaart" data-bewerk-dag data-mkaart '
                 f'data-mw="{mw_id}" data-datum="{datum}" aria-label="{titel} wijzigen">')
        sluit = "</button>"
    else:
        open_ = f'<div class="dag-kaart" data-mkaart data-mw="{mw_id}" data-datum="{datum}">'
        sluit = "</div>"
    tijden = f"{escape(d['begin'])} – {escape(d['eind'])}" if d["begin"] else ""
    tweede = ""
    t = d["tweede"]
    if t:
        tijden2 = f"{escape(t['begin'])} – {escape(t['eind'])}" if t["begin"] else ""
        tweede = (f'<span class="dk-tweede" data-m="tweede"><span class="dk-dienst" data-m="dienstnaam2" '
                  f'style="{escape(t["dienst_stijl"])}">{escape(t["dienstnaam"])}</span>'
                  f'<span class="dk-tijden" data-m="tijden2">{tijden2}</span>'
                  f'<span class="dk-uren" data-m="uren2">{escape(t["uren"])}</span></span>')
    opm = escape(d["opmerking"])
    if d["opm_begin"]:
        opm += f" ({escape(d['opm_begin'])}–{escape(d['opm_eind'])})"
    return Markup(
        f'{open_}<span class="dk-titel">{titel}</span>'
        f'<span class="dk-dienst" data-m="dienstnaam" style="{escape(d["dienst_stijl"])}">'
        f'{escape(d["dienstnaam"])}</span>'
        f'<span class="dk-tijden" data-m="tijden">{tijden}</span>'
        f'<span class="dk-uren" data-m="uren">{escape(d["uren"])}</span>{tweede}'
        f'<span class="dk-opm" data-m="opmerking" style="{escape(d["opmerking_stijl"])}">{opm}</span>'
        f'{sluit}')
