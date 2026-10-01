"""Roosterpatronen en sjablonen (Deel 4, versie 1.6.0). Alle testdata is fictief."""

import os
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import Dienst, Logboek, Medewerker, RoosterPatroon, SyncTaak
from app.services import patronen
from app.services.patronen import PatroonFout, UitrolKeuzes
from app.services.voorbeeldpakket import laad_voorbeeldpakket
from app.services.weekrooster import Wijziging, wijzig_cellen

MAANDAG = date(2026, 3, 2)  # week 10


@pytest.fixture
def mw(klaar):
    laad_voorbeeldpakket()
    medewerkers = [Medewerker(naam=f"Medewerker {x}", initialen=f"M{x}", volgorde=i)
                   for i, x in enumerate("ABC")]
    db.session.add_all(medewerkers)
    db.session.commit()
    return medewerkers


def _patroon(naam="Wisselend", weken=2, cellen=None) -> RoosterPatroon:
    patroon, fouten = patronen.sla_op(None, naam, weken, cellen or {(1, 0): "4", (2, 0): "7"})
    assert fouten == []
    return patroon


def _code(medewerker, datum, volgnummer=1):
    db.session.expire_all()
    dienst = Dienst.query.filter_by(medewerker_id=medewerker.id, datum=datum, volgnummer=volgnummer).first()
    return dienst.dienstcode.nummer if dienst is not None and dienst.dienstcode else None


def _keuzes(patroon, medewerkers, van, tot, **extra) -> UitrolKeuzes:
    return UitrolKeuzes(patroon.id, tuple(medewerkers), van, tot, **extra)


# ---------------------------------------------------------------------------
# Patroon maken, wijzigen, verwijderen
# ---------------------------------------------------------------------------

def test_patroon_maken_wijzigen_verwijderen(app, mw):
    patroon = _patroon(cellen={(1, 0): "4", (1, 1): "4 / 7", (2, 6): "5+17", (2, 2): ""})
    assert patroon.weken == 2 and patroon.cellen() == {(1, 0): "4", (1, 1): "4/7", (2, 6): "5/17"}
    patroon, fouten = patronen.sla_op(patroon, "Wisselend (nieuw)", 3, {(3, 4): "/3"})
    assert fouten == [] and patroon.naam == "Wisselend (nieuw)" and patroon.cellen() == {(3, 4): "/3"}
    assert Logboek.query.filter_by(actie="Roosterpatroon opgeslagen").count() == 2
    patronen.verwijder(patroon)
    assert RoosterPatroon.query.count() == 0
    assert Logboek.query.filter_by(actie="Roosterpatroon verwijderd").count() == 1


@pytest.mark.parametrize("naam, weken, cellen, melding", [
    ("X", 2, {(1, 0): "99"}, "Onbekende dienstcode: 99"),
    ("X", 2, {(1, 0): "abc"}, "geen dienstcode"),
    ("X", 2, {(1, 0): "1/2/3"}, "Hooguit 2 diensten"),
    ("X", 2, {(3, 0): "4"}, "week 3"),
    ("X", 2, {(1, 7): "4"}, "dag"),
    ("", 2, {}, "naam"),
    ("X", 0, {}, "1 t/m 12"),
    ("X", 13, {}, "1 t/m 12"),
    ("X", "acht", {}, "1 t/m 12"),
])
def test_ongeldige_patronen_geweigerd(app, mw, naam, weken, cellen, melding):
    patroon, fouten = patronen.sla_op(None, naam, weken, cellen)
    assert patroon is None and melding in " ".join(fouten), fouten
    assert RoosterPatroon.query.count() == 0


def test_dubbele_naam_geweigerd(app, mw):
    _patroon()
    _, fouten = patronen.sla_op(None, "wisselend", 2, {})
    assert "bestaat al" in " ".join(fouten)


def test_standaard_acht_weken():
    assert patronen.STANDAARD_WEKEN == 8 and patronen.MAX_WEKEN == 12


# ---------------------------------------------------------------------------
# Uitrollen
# ---------------------------------------------------------------------------

def test_cyclus_over_de_jaargrens_en_week_53(app, mw):
    patroon = _patroon()
    a = mw[0]
    keuzes = _keuzes(patroon, [(a.id, 1)], date(2026, 12, 21), date(2027, 1, 17))  # W52 2026 t/m W2 2027
    resultaat = patronen.pas_toe(patroon, keuzes)
    assert resultaat["nieuw"] == 4
    maandagen = (date(2026, 12, 21), date(2026, 12, 28), date(2027, 1, 4), date(2027, 1, 11))
    assert [_code(a, d) for d in maandagen] == [4, 7, 4, 7]  # W52, W53, W1, W2: de cyclus loopt door
    assert _code(a, date(2026, 12, 22)) is None  # dinsdag is vrij


def test_startpositie_per_medewerker(app, mw):
    patroon = _patroon(weken=3, cellen={(1, 0): "4", (2, 0): "7", (3, 0): "5"})
    starts = [(m.id, i + 1) for i, m in enumerate(mw)]
    keuzes = _keuzes(patroon, starts, MAANDAG, MAANDAG + timedelta(days=20))
    patronen.pas_toe(patroon, keuzes)
    weken = [MAANDAG, MAANDAG + timedelta(days=7), MAANDAG + timedelta(days=14)]
    assert [[_code(m, d) for d in weken] for m in mw] == [[4, 7, 5], [7, 5, 4], [5, 4, 7]]


def test_twee_codes_en_standaardtijden_uren_en_logboek(app, mw):
    patroon = _patroon(weken=1, cellen={(1, 0): "17/3", (1, 5): "4"})
    a = mw[0]
    patronen.pas_toe(patroon, _keuzes(patroon, [(a.id, 1)], MAANDAG, MAANDAG + timedelta(days=6)))
    d1, d2 = (Dienst.query.filter_by(medewerker_id=a.id, datum=MAANDAG, volgnummer=v).one() for v in (1, 2))
    assert (d1.dienstcode.nummer, d1.begin, d1.eind, d1.uren_berekend) == (17, "08:30", "12:30", 4.0)
    assert (d2.dienstcode.nummer, d2.begin, d2.eind, d2.uren_berekend) == (3, "14:30", "23:00", 8.0)
    zaterdag = Dienst.query.filter_by(medewerker_id=a.id, datum=MAANDAG + timedelta(days=5)).one()
    assert zaterdag.uren_berekend == 12
    regels = Logboek.query.filter_by(actie="Rooster gewijzigd").all()
    assert len(regels) == 3 and all("Roosterpatroon 'Wisselend'" in r.details for r in regels)
    assert {r.veld for r in regels} == {"dienst", "dienst 2"} and all(r.oude_waarde == "" for r in regels)
    assert Logboek.query.filter_by(actie="Roosterpatroon toegepast").count() == 1
    backups = os.listdir(os.path.join(app.config["DATA_MAP"], "backups"))
    assert any(n.endswith("-voor-patroon.db") for n in backups)


def test_overschrijven_tegenover_aanvullen(app, mw):
    a = mw[0]
    dinsdag = MAANDAG + timedelta(days=1)
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "5"), Wijziging(a.id, dinsdag, "code", "6"),
                          Wijziging(a.id, dinsdag, "opmerking", "Locatie A")])[1] == []
    patroon = _patroon(weken=1, cellen={(1, 0): "4", (1, 2): "7"})  # dinsdag vrij in het patroon
    week = (MAANDAG, MAANDAG + timedelta(days=6))
    aanvullen = _keuzes(patroon, [(a.id, 1)], *week, modus=patronen.MODUS_AANVULLEN)
    effect = patronen.effect(patroon, aanvullen)
    t = effect.per_medewerker[a.id]
    assert (t.nieuw, t.vervangen, t.verwijderd, t.overgeslagen) == (1, 0, 0, 1)  # wo nieuw, ma overgeslagen
    patronen.pas_toe(patroon, aanvullen)
    assert (_code(a, MAANDAG), _code(a, dinsdag), _code(a, MAANDAG + timedelta(days=2))) == (5, 6, 7)

    overschrijven = _keuzes(patroon, [(a.id, 1)], *week)
    t = patronen.effect(patroon, overschrijven).per_medewerker[a.id]
    assert (t.nieuw, t.vervangen, t.verwijderd, t.gelijk) == (0, 1, 1, 1)
    patronen.pas_toe(patroon, overschrijven)
    assert (_code(a, MAANDAG), _code(a, dinsdag)) == (4, None)
    # De opmerking hoort bij de dag en blijft staan; alleen de dienst gaat weg
    blijft = Dienst.query.filter_by(medewerker_id=a.id, datum=dinsdag).one()
    assert blijft.opmerking_tekst == "Locatie A" and blijft.dienstcode_id is None and blijft.begin is None


def test_feestdagen_overslaan_of_invullen(app, mw):
    koningsdag = date(2026, 4, 27)  # maandag
    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    a, b = mw[0], mw[1]
    van, tot = koningsdag - timedelta(days=7), koningsdag + timedelta(days=6)
    overslaan = _keuzes(patroon, [(a.id, 1)], van, tot, feestdagen=patronen.FEESTDAG_OVERSLAAN)
    assert patronen.effect(patroon, overslaan).per_medewerker[a.id].overgeslagen == 1
    patronen.pas_toe(patroon, overslaan)
    assert (_code(a, koningsdag - timedelta(days=7)), _code(a, koningsdag)) == (4, None)
    patronen.pas_toe(patroon, _keuzes(patroon, [(b.id, 1)], van, tot, feestdagen=patronen.FEESTDAG_INVULLEN))
    assert _code(b, koningsdag) == 4


def test_gearchiveerde_medewerker_krijgt_niets_vanaf_archiefdatum(app, mw):
    a = mw[0]
    a.gearchiveerd_vanaf = MAANDAG + timedelta(days=9)  # woensdag week 11
    db.session.commit()
    patroon = _patroon(weken=1, cellen={(1, d): "4" for d in range(7)})
    keuzes = _keuzes(patroon, [(a.id, 1)], MAANDAG, MAANDAG + timedelta(days=13))
    t = patronen.effect(patroon, keuzes).per_medewerker[a.id]
    assert (t.nieuw, t.overgeslagen) == (9, 5)
    patronen.pas_toe(patroon, keuzes)
    assert _code(a, MAANDAG + timedelta(days=8)) == 4 and _code(a, MAANDAG + timedelta(days=9)) is None


def test_herhaald_toepassen_is_idempotent(app, mw):
    patroon = _patroon(weken=2, cellen={(1, 0): "4/7", (1, 3): "5", (2, 1): "6"})
    starts = [(m.id, i + 1) for i, m in enumerate(mw[:2])]
    keuzes = _keuzes(patroon, starts, MAANDAG, MAANDAG + timedelta(days=27))
    eerste = patronen.pas_toe(patroon, keuzes)
    voor = sorted((d.medewerker_id, d.datum, d.volgnummer, d.dienstcode_id, d.versie, d.uren_berekend)
                  for d in Dienst.query.all())
    regels = Logboek.query.filter_by(actie="Rooster gewijzigd").count()
    tweede = patronen.pas_toe(patroon, keuzes)
    assert eerste["nieuw"] > 0 and tweede["nieuw"] == tweede["vervangen"] == tweede["verwijderd"] == 0
    assert tweede["gelijk"] == eerste["nieuw"]
    db.session.expire_all()
    assert sorted((d.medewerker_id, d.datum, d.volgnummer, d.dienstcode_id, d.versie, d.uren_berekend)
                  for d in Dienst.query.all()) == voor
    assert Logboek.query.filter_by(actie="Rooster gewijzigd").count() == regels


def test_droogloop_gelijk_aan_resultaat(app, mw):
    a, b = mw[0], mw[1]
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "5"),
                          Wijziging(b.id, MAANDAG + timedelta(days=1), "code", "4/7")])[1] == []
    patroon = _patroon(weken=2, cellen={(1, 0): "4", (1, 1): "17", (2, 2): "4/7"})
    keuzes = _keuzes(patroon, [(a.id, 1), (b.id, 2)], MAANDAG, MAANDAG + timedelta(days=20))
    effect = patronen.effect(patroon, keuzes)
    voorspeld = effect.totaal
    resultaat = patronen.pas_toe(patroon, keuzes)
    assert resultaat == {s: getattr(voorspeld, s) for s in ("nieuw", "vervangen", "verwijderd", "gelijk",
                                                             "overgeslagen")}
    # En na het toepassen: alles gelijk aan wat het patroon voorschrijft
    na = patronen.effect(patroon, keuzes).totaal
    assert na.nieuw == na.vervangen == na.verwijderd == 0


def test_alleen_geraakte_medewerkers_naar_google(app, mw):
    a, b = mw[0], mw[1]
    for m in (a, b):
        m.agenda_modus, m.agenda_id = "B", f"agenda-{m.initialen}"
    db.session.commit()
    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    patronen.pas_toe(patroon, _keuzes(patroon, [(a.id, 1)], MAANDAG, MAANDAG + timedelta(days=6)))
    assert {t.medewerker_id for t in SyncTaak.query.all()} == {a.id}


def test_verwijderde_dienst_met_google_afspraak_blijft_leeg_staan(app, mw):
    a = mw[0]
    wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "5")])
    dienst = Dienst.query.filter_by(medewerker_id=a.id, datum=MAANDAG).one()
    dienst.google_event_id = "afspraak-1"
    db.session.commit()
    patroon = _patroon(weken=1, cellen={(1, 1): "4"})  # maandag vrij
    patronen.pas_toe(patroon, _keuzes(patroon, [(a.id, 1)], MAANDAG, MAANDAG + timedelta(days=6)))
    db.session.expire_all()
    blijft = Dienst.query.filter_by(medewerker_id=a.id, datum=MAANDAG).one()
    assert blijft.is_leeg and blijft.google_event_id == "afspraak-1"


@pytest.mark.parametrize("wijziging, melding", [
    ({"medewerkers": ()}, "minstens één medewerker"),
    ({"medewerkers": ((999, 1),)}, "Onbekende medewerker"),
    ({"medewerkers": ((1, 3),)}, "startpositie"),
    ({"tot": date(2026, 3, 1)}, "na de startweek"),
    ({"tot": date(2028, 6, 1)}, "hooguit"),
    ({"modus": "alles"}, "modus"),
    ({"feestdagen": "soms"}, "feestdagen"),
])
def test_ongeldige_uitrol(app, mw, wijziging, melding):
    patroon = _patroon()
    gegevens = {"medewerkers": ((mw[0].id, 1),), "van": MAANDAG, "tot": MAANDAG + timedelta(days=6),
                **wijziging}
    keuzes = UitrolKeuzes(patroon.id, gegevens["medewerkers"], gegevens["van"], gegevens["tot"],
                          gegevens.get("modus", patronen.MODUS_OVERSCHRIJVEN),
                          gegevens.get("feestdagen", patronen.FEESTDAG_INVULLEN))
    assert melding in " ".join(keuzes.controleer(patroon))
    with pytest.raises(PatroonFout):
        patronen.pas_toe(patroon, keuzes)
    assert Dienst.query.count() == 0


def test_code_inmiddels_ongeldig_wordt_bij_toepassen_geweigerd(app, mw):
    from app.models import Dienstcode

    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    Dienstcode.query.filter_by(nummer=4).one().actief = False
    db.session.commit()
    keuzes = _keuzes(patroon, [(mw[0].id, 1)], MAANDAG, MAANDAG + timedelta(days=6))
    assert "Onbekende dienstcode: 4" in " ".join(keuzes.controleer(patroon))


# ---------------------------------------------------------------------------
# Sjabloon uit het rooster
# ---------------------------------------------------------------------------

def test_sjabloon_uit_een_bestaande_periode(app, mw):
    a = mw[0]
    volgende = MAANDAG + timedelta(days=7)
    assert wijzig_cellen([
        Wijziging(a.id, MAANDAG, "code", "4"), Wijziging(a.id, MAANDAG + timedelta(days=2), "code", "17/3"),
        Wijziging(a.id, volgende + timedelta(days=4), "code", "5"),
        Wijziging(a.id, volgende + timedelta(days=5), "dienstnaam", "Cursus extern"),  # zonder code: vrij
        Wijziging(mw[1].id, MAANDAG, "code", "7"),  # andere medewerker: telt niet mee
    ])[1] == []
    cellen, weken, waarschuwingen = patronen.sjabloon(a, MAANDAG, volgende)
    assert weken == 2 and cellen == {(1, 0): "4", (1, 2): "17/3", (2, 4): "5"}
    assert any("zonder code" in w for w in waarschuwingen)
    patroon, fouten = patronen.sla_op(None, "Uit het rooster", weken, cellen)
    assert fouten == []
    # Terugzetten op dezelfde plek verandert niets
    t = patronen.effect(patroon, _keuzes(patroon, [(a.id, 1)], MAANDAG, volgende + timedelta(days=6))).totaal
    assert (t.nieuw, t.vervangen) == (0, 0) and t.gelijk == 4
    with pytest.raises(PatroonFout):
        patronen.sjabloon(a, MAANDAG, MAANDAG + timedelta(weeks=12))  # 13 weken: te lang
    with pytest.raises(PatroonFout):
        patronen.sjabloon(a, volgende, MAANDAG)


# ---------------------------------------------------------------------------
# Schermen (Beheer → Roosterpatronen)
# ---------------------------------------------------------------------------

def _raster(**cellen):
    return {f"c-{k[1:].replace('_', '-')}": v for k, v in cellen.items()}


def test_scherm_patroon_maken_en_fouten(app, als_beheerder, mw):
    assert "Nieuw patroon" in als_beheerder.get("/beheer/patronen").data.decode()
    pagina = als_beheerder.get("/beheer/patronen/nieuw").data.decode()
    assert 'name="weken" value="8"' in pagina and 'name="c-8-6"' in pagina  # standaard 8 weken
    # Ongeldige code: melding, niets opgeslagen, ingevulde waarden blijven staan
    antwoord = als_beheerder.post("/beheer/patronen/nieuw", data={
        "naam": "Vroeg-laat", "weken": "2", "actie": "opslaan", **_raster(w1_0="4", w2_3="99")})
    tekst = antwoord.data.decode()
    assert antwoord.status_code == 400 and "Onbekende dienstcode: 99" in tekst and 'value="99"' in tekst
    assert RoosterPatroon.query.count() == 0
    # Aantal weken aanpassen zonder opslaan
    tekst = als_beheerder.post("/beheer/patronen/nieuw", data={
        "naam": "Vroeg-laat", "weken": "3", "actie": "weken", **_raster(w1_0="4")}).data.decode()
    assert 'name="c-3-6"' in tekst and 'name="c-4-0"' not in tekst and RoosterPatroon.query.count() == 0
    antwoord = als_beheerder.post("/beheer/patronen/nieuw", data={
        "naam": "Vroeg-laat", "weken": "2", "actie": "opslaan", **_raster(w1_0="4", w2_3="4 / 7", w3_0="5")})
    assert antwoord.status_code == 302
    patroon = RoosterPatroon.query.one()
    assert patroon.cellen() == {(1, 0): "4", (2, 3): "4/7"}  # week 3 valt buiten de 2 weken
    assert 'value="4/7"' in als_beheerder.get(f"/beheer/patronen/{patroon.id}").data.decode()
    als_beheerder.post(f"/beheer/patronen/{patroon.id}/verwijderen")
    assert RoosterPatroon.query.count() == 0


def test_scherm_sjabloon(app, als_beheerder, mw):
    a = mw[0]
    wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "4"),
                   Wijziging(a.id, MAANDAG + timedelta(days=8), "code", "7")])
    tekst = als_beheerder.post("/beheer/patronen/sjabloon", data={
        "medewerker": a.id, "van": "2026-W10", "tot": "2026-W11"}).data.decode()
    assert 'name="naam" value="MA W10-W11 2026"' in tekst and 'name="weken" value="2"' in tekst
    assert 'name="c-1-0" value="4"' in tekst and 'name="c-2-1" value="7"' in tekst
    assert RoosterPatroon.query.count() == 0  # nog niet opgeslagen
    for fout in ({"medewerker": "", "van": "2026-W10", "tot": "2026-W11"},
                 {"medewerker": a.id, "van": "2026-W60", "tot": "2026-W11"},
                 {"medewerker": a.id, "van": "2026-W01", "tot": "2026-W20"}):
        antwoord = als_beheerder.post("/beheer/patronen/sjabloon", data=fout, follow_redirects=True)
        assert antwoord.status_code == 200 and 'class="melding fout"' in antwoord.data.decode(), fout


def test_scherm_uitrollen_met_droogloop_en_bevestigen(app, als_beheerder, mw):
    a, b = mw[0], mw[1]
    patroon = _patroon()
    url = f"/beheer/patronen/{patroon.id}/uitrollen"
    keuzes = {"mw": [a.id, b.id], f"start-{a.id}": "1", f"start-{b.id}": "2", "van": "2026-W10",
              "tot_week": "2026-W11", "modus": "overschrijven", "feestdagen": "invullen"}
    assert "Voorbeeld bijwerken" in als_beheerder.get(url).data.decode()
    pagina = als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    pagina = pagina.data.decode()
    assert "Totaal: <strong>4</strong> nieuw" in pagina and "Medewerker B" in pagina
    assert Dienst.query.count() == 0  # droogloop: niets opgeslagen
    # Andere keuzes dan het voorbeeld: niet toepassen
    anders = {**keuzes, f"start-{b.id}": "1", "actie": "toepassen", "bevestig": "1"}
    antwoord = als_beheerder.post(url, data=anders, follow_redirects=True)
    assert "gewijzigd sinds het voorbeeld" in antwoord.data.decode() and Dienst.query.count() == 0
    # Zonder bevestiging: niet toepassen
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen"}, follow_redirects=True)
    assert "bevestiging" in antwoord.data.decode() and Dienst.query.count() == 0
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"})
    assert antwoord.status_code == 302 and "/week/2026/10" in antwoord.headers["Location"]
    assert [_code(a, MAANDAG), _code(a, MAANDAG + timedelta(days=7))] == [4, 7]
    assert [_code(b, MAANDAG), _code(b, MAANDAG + timedelta(days=7))] == [7, 4]


@pytest.mark.parametrize("wijziging, melding", [
    ({"van": "onzin"}, "geldige startweek"),
    ({"tot_week": "", "tot_datum": ""}, "eindweek of een einddatum"),
    ({"mw": ["abc"]}, "Onbekende medewerker"),
    ({"modus": "alles"}, "modus"),
    ({"tot_datum": "2026-03-01"}, "na de startweek"),
])
def test_scherm_uitrollen_ongeldig_geeft_melding(app, als_beheerder, mw, wijziging, melding):
    patroon = _patroon()
    data = {"mw": [mw[0].id], "van": "2026-W10", "tot_week": "2026-W11", "modus": "overschrijven",
            "feestdagen": "invullen", "actie": "voorbeeld", **wijziging}
    url = f"/beheer/patronen/{patroon.id}/uitrollen"
    antwoord = als_beheerder.post(url, data=data, follow_redirects=True)
    assert antwoord.status_code == 200 and melding in antwoord.data.decode()


def test_schermen_alleen_beheerder(app, client, mw):
    from .conftest import login

    patroon = _patroon()
    login(client, "collega")
    for url in ("/beheer/patronen", "/beheer/patronen/nieuw", f"/beheer/patronen/{patroon.id}",
                f"/beheer/patronen/{patroon.id}/uitrollen"):
        assert client.get(url).status_code == 403, url
