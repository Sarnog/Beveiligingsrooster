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


# ---------------------------------------------------------------------------
# Week kopiëren binnen een patroon (8-wekelijks rooster: plan één week, kopieer naar andere)
# ---------------------------------------------------------------------------

def test_kopieer_week_naar_andere_weken():
    cellen = {(1, 0): "4", (1, 5): "4/7", (3, 2): "5", (2, 1): "6"}
    nieuw = patronen.kopieer_week(cellen, 1, [3, 5, 7, 1], 8)
    assert nieuw == {(1, 0): "4", (1, 5): "4/7", (2, 1): "6",
                     **{(w, d): cellen.get((1, d), "") for w in (3, 5, 7) for d in range(7)}}
    assert nieuw[(3, 2)] == ""  # een lege dag in de bronweek maakt de doelweek ook leeg
    assert cellen[(3, 2)] == "5"  # het origineel blijft ongewijzigd


@pytest.mark.parametrize("bron, naar, melding", [
    (0, [2], "bronweek van 1 t/m 8"),
    (9, [2], "bronweek van 1 t/m 8"),
    (1, [], "minstens één andere week"),
    (1, [1], "minstens één andere week"),
    (1, [2, 9], "kies weken van 1 t/m 8"),
])
def test_kopieer_week_ongeldig(bron, naar, melding):
    with pytest.raises(PatroonFout, match=melding):
        patronen.kopieer_week({}, bron, naar, 8)


def test_scherm_week_kopieren(app, als_beheerder, mw):
    pagina = als_beheerder.get("/beheer/patronen/nieuw").data.decode()
    assert "data-week-kopieren" in pagina and 'name="kopieer_naar" value="8"' in pagina
    antwoord = als_beheerder.post("/beheer/patronen/nieuw", data={
        "naam": "Acht weken", "weken": "8", "actie": "kopieer", "kopieer_van": "1",
        "kopieer_naar": ["2", "3", "8", "x"], **_raster(w1_0="4", w1_6="4/7", w2_3="5")})
    tekst = antwoord.data.decode()
    assert antwoord.status_code == 200 and "Week 1 gekopieerd naar week 2, 3, 8" in tekst
    for week in (2, 3, 8):
        assert f'name="c-{week}-0" value="4"' in tekst and f'name="c-{week}-6" value="4/7"' in tekst
    assert 'name="c-2-3" value=""' in tekst and 'name="c-4-0" value=""' in tekst
    assert RoosterPatroon.query.count() == 0  # nog niet opgeslagen
    # Fout: geen doelweek, of een onzinnige bronweek
    for data in ({"kopieer_van": "1"}, {"kopieer_van": "abc", "kopieer_naar": "2"}):
        antwoord = als_beheerder.post("/beheer/patronen/nieuw", data={
            "naam": "Acht weken", "weken": "8", "actie": "kopieer", **data, **_raster(w1_0="4")})
        assert antwoord.status_code == 400 and 'class="melding fout"' in antwoord.data.decode()
        assert 'name="c-1-0" value="4"' in antwoord.data.decode()  # ingevulde waarden blijven staan


def test_scherm_ongeldig_aantal_weken_toepassen(app, als_beheerder, mw):
    antwoord = als_beheerder.post("/beheer/patronen/nieuw",
                                  data={"naam": "X", "weken": "20", "actie": "weken"})
    tekst = antwoord.data.decode()
    assert "1 t/m 12 weken" in tekst and 'name="c-8-6"' in tekst  # terug naar de standaard 8


# ---------------------------------------------------------------------------
# Rooster herhalen: een 8-wekelijks rooster uit het weekrooster herhalen
# ---------------------------------------------------------------------------

def _plan_acht_weken(medewerkers):
    """Elke medewerker een eigen code op maandag van elke week 1..8 vanaf MAANDAG."""
    codes = ["4", "5", "6", "7", "17", "3", "4/7", ""]
    wijzigingen = [Wijziging(m.id, MAANDAG + timedelta(weeks=w), "code", codes[(w + i) % 8])
                   for i, m in enumerate(medewerkers) for w in range(8) if codes[(w + i) % 8]]
    assert wijzig_cellen(wijzigingen)[1] == []
    return codes


def _herhaal(medewerkers, van, tot, **extra):
    return patronen.HerhaalKeuzes(tuple(m.id for m in medewerkers), MAANDAG, extra.pop("weken", 8), van, tot,
                                  **extra)


def _cel(medewerker, datum):
    db.session.expire_all()
    diensten = {d.volgnummer: d for d in Dienst.query.filter_by(medewerker_id=medewerker.id, datum=datum)}
    return "/".join(str(diensten[v].dienstcode.nummer) if v in diensten and diensten[v].dienstcode else ""
                    for v in (1, 2)).rstrip("/")


def test_herhalen_acht_weken_voor_het_hele_team(app, mw):
    codes = _plan_acht_weken(mw)
    van = MAANDAG + timedelta(weeks=8)
    keuzes = _herhaal(mw, van, van + timedelta(weeks=16, days=-1))  # twee keer de cyclus
    assert keuzes.controleer() == [] and keuzes.startpositie == 1
    effect = patronen.herhaal_effect(keuzes)
    resultaat = patronen.herhaal_pas_toe(keuzes)
    assert resultaat["nieuw"] == effect.totaal.nieuw == 2 * 3 * 8  # 7 dagen met dienst (één met 2) per cyclus
    for i, m in enumerate(mw):
        for w in range(16):
            assert _cel(m, van + timedelta(weeks=w)) == codes[(w + i) % 8], (m.naam, w)
    assert Logboek.query.filter_by(actie="Rooster herhaald").count() == 1
    assert "start in week 1" in Logboek.query.filter_by(actie="Rooster herhaald").one().details
    backups = os.listdir(os.path.join(app.config["DATA_MAP"], "backups"))
    assert any(n.endswith("-voor-herhalen.db") for n in backups)
    # Nogmaals: niets verandert
    tweede = patronen.herhaal_pas_toe(keuzes)
    assert tweede["nieuw"] == tweede["vervangen"] == tweede["verwijderd"] == 0


def test_herhalen_cyclus_loopt_door_vanaf_de_bronweken(app, mw):
    a = mw[0]
    codes = _plan_acht_weken([a])
    van = MAANDAG + timedelta(weeks=11)  # 11 weken na bronweek 1 = week 4 van de cyclus
    keuzes = _herhaal([a], van, van + timedelta(days=6 + 7))
    assert keuzes.startpositie == 4
    patronen.herhaal_pas_toe(keuzes)
    assert [_cel(a, van), _cel(a, van + timedelta(weeks=1))] == [codes[3], codes[4]]
    # Ook vóór de bronweken: de cyclus loopt terug door
    eerder = MAANDAG - timedelta(weeks=3)
    terug = _herhaal([a], eerder, eerder + timedelta(days=6))
    assert terug.startpositie == 6
    patronen.herhaal_pas_toe(terug)
    assert _cel(a, eerder) == codes[5]


def test_herhalen_wist_vrije_dagen_en_houdt_opmerking(app, mw):
    a = mw[0]
    _plan_acht_weken([a])
    doel = MAANDAG + timedelta(weeks=15)  # week 8 van de cyclus: vrij
    assert wijzig_cellen([Wijziging(a.id, doel, "code", "5"),
                          Wijziging(a.id, doel, "opmerking", "Locatie A")])[1] == []
    keuzes = _herhaal([a], MAANDAG + timedelta(weeks=8), MAANDAG + timedelta(weeks=16, days=-1))
    t = patronen.herhaal_effect(keuzes).per_medewerker[a.id]
    assert t.verwijderd == 1
    patronen.herhaal_pas_toe(keuzes)
    blijft = Dienst.query.filter_by(medewerker_id=a.id, datum=doel).one()
    assert blijft.dienstcode_id is None and blijft.opmerking_tekst == "Locatie A"
    # Aanvullen laat bestaande diensten staan
    assert wijzig_cellen([Wijziging(a.id, doel, "code", "5")])[1] == []
    aanvullen = _herhaal([a], MAANDAG + timedelta(weeks=8), MAANDAG + timedelta(weeks=16, days=-1),
                         modus=patronen.MODUS_AANVULLEN)
    assert patronen.herhaal_effect(aanvullen).per_medewerker[a.id].overgeslagen >= 1
    patronen.herhaal_pas_toe(aanvullen)
    assert _cel(a, doel) == "5"


def test_herhalen_waarschuwt_voor_dienst_zonder_code(app, mw):
    a = mw[0]
    woensdag = MAANDAG + timedelta(days=2)
    assert wijzig_cellen([Wijziging(a.id, woensdag, "dienstnaam", "Cursus extern")])[1] == []
    keuzes = _herhaal([a], MAANDAG + timedelta(weeks=8), MAANDAG + timedelta(weeks=8, days=6))
    effect = patronen.herhaal_effect(keuzes)
    assert any("Medewerker A" in w and "zonder code" in w for w in effect.waarschuwingen)


@pytest.mark.parametrize("wijziging, melding", [
    ({"medewerkers": ()}, "minstens één medewerker"),
    ({"medewerkers": (1, 1)}, "maar één keer"),
    ({"medewerkers": (999,)}, "Onbekende medewerker"),
    ({"weken": 0}, "1 t/m 12"),
    ({"weken": 13}, "1 t/m 12"),
    ({"bron": date(1900, 1, 1)}, "Kies weken tussen"),
    ({"bron": MAANDAG + timedelta(days=1)}, "maandag"),
    ({"van": MAANDAG + timedelta(weeks=8, days=1)}, "maandag"),
    ({"tot": MAANDAG + timedelta(weeks=7)}, "na de startweek"),
    ({"tot": MAANDAG + timedelta(weeks=8 + 106)}, "hooguit"),
    ({"van": MAANDAG + timedelta(weeks=7)}, "overlapt de bronweken"),
    ({"van": MAANDAG - timedelta(weeks=1), "tot": MAANDAG}, "overlapt de bronweken"),
    ({"modus": "alles"}, "modus"),
    ({"feestdagen": "soms"}, "feestdagen"),
])
def test_herhalen_ongeldig(app, mw, wijziging, melding):
    gegevens = {"medewerkers": (mw[0].id,), "bron": MAANDAG, "weken": 8, "van": MAANDAG + timedelta(weeks=8),
                "tot": MAANDAG + timedelta(weeks=9, days=-1), "modus": patronen.MODUS_OVERSCHRIJVEN,
                "feestdagen": patronen.FEESTDAG_INVULLEN, **wijziging}
    keuzes = patronen.HerhaalKeuzes(**gegevens)
    assert melding in " ".join(keuzes.controleer()), keuzes.controleer()
    with pytest.raises(PatroonFout):
        patronen.herhaal_pas_toe(keuzes)
    assert Dienst.query.count() == 0


def test_herhalen_als_dict_en_terug(app, mw):
    keuzes = _herhaal(mw, MAANDAG + timedelta(weeks=8), MAANDAG + timedelta(weeks=9, days=-1))
    assert patronen.HerhaalKeuzes.uit_dict(keuzes.als_dict()) == keuzes
    assert keuzes.bron_tot == MAANDAG + timedelta(weeks=8, days=-1)
    assert "Medewerker B" in keuzes.beschrijving({m.id: m.naam for m in mw})
    assert "999" in patronen.HerhaalKeuzes((999,), MAANDAG, 8, keuzes.van, keuzes.tot).beschrijving({})


def test_scherm_rooster_herhalen(app, als_beheerder, mw):
    a, b, c = mw
    c.gearchiveerd_vanaf = MAANDAG  # vóór de standaard startweek: standaard niet gekozen
    db.session.commit()
    codes = _plan_acht_weken([a, b])
    url = "/beheer/patronen/herhalen"
    assert "data-herhalen-kaart" in als_beheerder.get("/beheer/patronen").data.decode()
    pagina = als_beheerder.get(url).data.decode()
    assert 'name="weken" value="8"' in pagina and "Voorbeeld bijwerken" in pagina
    assert f'value="{c.id}" checked' not in pagina  # standaardkeuze: zie ..._met_bronrooster
    keuzes = {"mw": [a.id, b.id], "bron": "2026-W10", "weken": "8", "van": "2026-W18",
              "tot_week": "2026-W25", "modus": "overschrijven", "feestdagen": "invullen"}
    pagina = als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    tekst = pagina.data.decode()
    assert "data-herhaal-uitleg" in tekst and "week 1 van de cyclus" in tekst and "Medewerker B" in tekst
    assert Dienst.query.filter(Dienst.datum >= date(2026, 4, 27)).count() == 0  # droogloop
    # Andere keuzes dan het voorbeeld, of zonder bevestiging: niet toepassen
    antwoord = als_beheerder.post(url, data={**keuzes, "weken": "4", "actie": "toepassen", "bevestig": "1"},
                                  follow_redirects=True)
    assert "gewijzigd sinds het voorbeeld" in antwoord.data.decode()
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen"}, follow_redirects=True)
    assert "bevestiging" in antwoord.data.decode()
    assert Dienst.query.filter(Dienst.datum >= date(2026, 4, 27)).count() == 0
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"})
    assert antwoord.status_code == 302 and "/week/2026/18" in antwoord.headers["Location"]
    assert [_cel(a, MAANDAG + timedelta(weeks=8 + w)) for w in range(8)] == codes
    assert _cel(b, MAANDAG + timedelta(weeks=8)) == codes[1]
    assert "data-herhaal-uitleg" not in als_beheerder.get(url).data.decode()  # keuzes vergeten


def test_scherm_rooster_herhalen_einddatum_en_waarschuwing(app, als_beheerder, mw):
    a = mw[0]
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "dienstnaam", "Cursus extern")])[1] == []
    url = "/beheer/patronen/herhalen"
    als_beheerder.post(url, data={"mw": [a.id], "bron": "2026-W10", "weken": "2", "van": "2026-W12",
                                  "tot_datum": "2026-03-20", "modus": "overschrijven",
                                  "feestdagen": "invullen", "actie": "voorbeeld"})
    tekst = als_beheerder.get(url).data.decode()
    assert "t/m 20-03-2026" in tekst and "data-waarschuwingen" in tekst and 'value="2026-03-20"' in tekst


@pytest.mark.parametrize("wijziging, melding", [
    ({"bron": "onzin"}, "geldige eerste bronweek"),
    ({"van": "2026-W99"}, "geldige startweek"),
    ({"weken": "negen"}, "Herhaal 1 t/m 12 weken"),
    ({"tot_week": "", "tot_datum": ""}, "eindweek of een einddatum"),
    ({"mw": ["abc"]}, "Onbekende medewerker"),
    ({"van": "2026-W11"}, "overlapt de bronweken"),
])
def test_scherm_rooster_herhalen_ongeldig(app, als_beheerder, mw, wijziging, melding):
    data = {"mw": [mw[0].id], "bron": "2026-W10", "weken": "8", "van": "2026-W18", "tot_week": "2026-W25",
            "modus": "overschrijven", "feestdagen": "invullen", "actie": "voorbeeld", **wijziging}
    antwoord = als_beheerder.post("/beheer/patronen/herhalen", data=data, follow_redirects=True)
    tekst = antwoord.data.decode()
    assert antwoord.status_code == 200 and melding in tekst and "data-herhaal-uitleg" not in tekst


def test_scherm_rooster_herhalen_toepassen_mislukt(app, als_beheerder, mw, monkeypatch):
    url = "/beheer/patronen/herhalen"
    keuzes = {"mw": [mw[0].id], "bron": "2026-W10", "weken": "8", "van": "2026-W18", "tot_week": "2026-W18",
              "modus": "overschrijven", "feestdagen": "invullen"}

    def kapot(_keuzes, _afdruk):
        raise RuntimeError("schijf vol")

    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    monkeypatch.setattr(patronen, "herhaal_pas_toe", kapot)
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                                  follow_redirects=True)
    assert "Het herhalen is mislukt; er is niets gewijzigd (RuntimeError)" in antwoord.data.decode()

    def ongeldig(_keuzes, _afdruk):
        raise PatroonFout("Er is niets gewijzigd: test")

    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
    monkeypatch.setattr(patronen, "herhaal_pas_toe", ongeldig)
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                                  follow_redirects=True)
    assert "Er is niets gewijzigd: test" in antwoord.data.decode()


def test_scherm_rooster_herhalen_verlopen_keuzes_in_sessie(app, als_beheerder, mw):
    """Bewaarde keuzes die niet meer kloppen (medewerker weg) geven geen voorbeeld en worden vergeten."""
    with als_beheerder.session_transaction() as sessie:
        van = MAANDAG + timedelta(weeks=8)
        keuzes = patronen.HerhaalKeuzes((999,), MAANDAG, 8, van, van + timedelta(days=6))
        sessie["herhaal_keuzes"] = keuzes.als_dict()
    assert "data-herhaal-uitleg" not in als_beheerder.get("/beheer/patronen/herhalen").data.decode()
    with als_beheerder.session_transaction() as sessie:
        assert "herhaal_keuzes" not in sessie


def test_scherm_uitrollen_toepassen_mislukt(app, als_beheerder, mw, monkeypatch):
    patroon = _patroon()
    url = f"/beheer/patronen/{patroon.id}/uitrollen"
    keuzes = {"mw": [mw[0].id], f"start-{mw[0].id}": "1", "van": "2026-W10", "tot_week": "2026-W11",
              "modus": "overschrijven", "feestdagen": "invullen"}
    for fout, melding in ((RuntimeError("weg"), "mislukt; er is niets gewijzigd (RuntimeError)"),
                          (PatroonFout("Er is niets gewijzigd: test"), "Er is niets gewijzigd: test")):
        def kapot(_patroon, _keuzes, _afdruk, fout=fout):
            raise fout

        als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"})
        monkeypatch.setattr(patronen, "pas_toe", kapot)
        antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                                      follow_redirects=True)
        assert melding in antwoord.data.decode()


def test_schermen_herhalen_alleen_beheerder(app, als_gebruiker, mw):
    assert als_gebruiker.get("/beheer/patronen/herhalen").status_code == 403
    assert als_gebruiker.post("/beheer/patronen/herhalen", data={"actie": "toepassen"}).status_code == 403


def test_toepassen_mislukt_draait_alles_terug(app, mw, monkeypatch):
    """Een fout halverwege: rollback, niets opgeslagen (ook geen logboekregel)."""
    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    monkeypatch.setattr(patronen, "markeer_bijgewerkt", lambda: (_ for _ in ()).throw(RuntimeError("weg")))
    with pytest.raises(RuntimeError):
        patronen.pas_toe(patroon, _keuzes(patroon, [(mw[0].id, 1)], MAANDAG, MAANDAG + timedelta(days=6)))
    assert Dienst.query.count() == 0
    assert Logboek.query.filter_by(actie="Roosterpatroon toegepast").count() == 0


# ---------------------------------------------------------------------------
# Randgevallen (volledige branch-coverage van services/patronen.py)
# ---------------------------------------------------------------------------

def test_blanco_code_in_patroon_telt_als_vrij(app, mw):
    from app.services import instellingen

    patroon = _patroon(cellen={(1, 0): str(instellingen.blanco_code()), (1, 1): "4"})
    assert patroon.cellen() == {(1, 1): "4"}


def test_sjabloon_slaat_lege_regels_en_ongeldige_codes_over(app, mw):
    from app.models import Dienstcode

    a = mw[0]
    assert wijzig_cellen([Wijziging(a.id, MAANDAG, "code", "4"),
                          Wijziging(a.id, MAANDAG + timedelta(days=1), "code", "5")])[1] == []
    db.session.add(Dienst(medewerker_id=a.id, datum=MAANDAG + timedelta(days=2), volgnummer=1, versie=1,
                          google_event_id="afspraak-1"))  # lege regel die op de agenda wacht
    Dienstcode.query.filter_by(nummer=4).one().actief = False
    db.session.commit()
    cellen, weken, waarschuwingen = patronen.sjabloon(a, MAANDAG, MAANDAG)
    assert (cellen, weken) == ({(1, 1): "5"}, 1)
    assert any("02-03-2026" in w and "telt als vrij" in w for w in waarschuwingen)


@pytest.mark.parametrize("wijziging, melding", [
    ({"patroon_id": 999}, "Onbekend patroon"),
    ({"medewerkers": ((1, 1), (1, 2))}, "maar één keer"),
    ({"van": date(1900, 1, 1)}, "Kies een periode tussen"),
    ({"van": MAANDAG + timedelta(days=1)}, "maandag"),
])
def test_ongeldige_uitrol_overig(app, mw, wijziging, melding):
    patroon = _patroon()
    gegevens = {"patroon_id": patroon.id, "medewerkers": ((mw[0].id, 1),), "van": MAANDAG,
                "tot": MAANDAG + timedelta(days=6), **wijziging}
    assert melding in " ".join(UitrolKeuzes(**gegevens).controleer(patroon))
    assert UitrolKeuzes(**gegevens).controleer(None) == ["Onbekend patroon."]


def test_effect_slaat_onbekende_medewerker_over(app, mw):
    patroon = _patroon(weken=1, cellen={(1, 0): "4"})
    effect = patronen.effect(patroon, _keuzes(patroon, [(999, 1), (mw[0].id, 1)], MAANDAG,
                                              MAANDAG + timedelta(days=6)))
    assert list(effect.per_medewerker) == [mw[0].id] and effect.totaal.nieuw == 1
    assert patronen.effect(patroon, _keuzes(patroon, [], MAANDAG, MAANDAG)).acties == []


# ---------------------------------------------------------------------------
# Bestaand patroon opnieuw opslaan (audit: IntegrityError op uq_patroon_week_dag)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nieuwe_cellen", [
    {(1, 0): "4", (2, 0): "7"},  # ongewijzigd
    {(1, 0): "5", (2, 0): "7"},  # gewijzigde cel
    {(1, 0): "4", (2, 0): "7", (1, 3): "4/7"},  # extra cel
    {(1, 0): "", (2, 0): ""},  # alle cellen leeg
], ids=["ongewijzigd", "gewijzigd", "extra", "leeg"])
def test_bestaand_patroon_opnieuw_opslaan(app, mw, nieuwe_cellen):
    patroon = _patroon()
    opgeslagen, fouten = patronen.sla_op(patroon, patroon.naam, 2, nieuwe_cellen)
    assert fouten == [] and opgeslagen is patroon
    db.session.expire_all()
    verwacht = {k: v for k, v in nieuwe_cellen.items() if v}
    assert RoosterPatroon.query.one().cellen() == verwacht


@pytest.mark.parametrize("raster, verwacht", [
    ({"w1_0": "4", "w2_0": "7"}, {(1, 0): "4", (2, 0): "7"}),
    ({"w1_0": "5", "w2_0": "7"}, {(1, 0): "5", (2, 0): "7"}),
    ({"w1_0": "4", "w2_0": "7", "w1_3": "4/7"}, {(1, 0): "4", (2, 0): "7", (1, 3): "4/7"}),
    ({}, {}),
], ids=["ongewijzigd", "gewijzigd", "extra", "leeg"])
def test_scherm_bestaand_patroon_opnieuw_opslaan(app, als_beheerder, mw, raster, verwacht):
    patroon = _patroon()
    antwoord = als_beheerder.post(f"/beheer/patronen/{patroon.id}", data={
        "naam": patroon.naam, "weken": "2", "actie": "opslaan", **_raster(**raster)})
    assert antwoord.status_code == 302
    db.session.expire_all()
    assert RoosterPatroon.query.one().cellen() == verwacht


def test_scherm_week_kopieren_en_opslaan_bestaand_patroon(app, als_beheerder, mw):
    patroon = _patroon(weken=3, cellen={(1, 0): "4", (2, 0): "7", (3, 0): "5"})
    url = f"/beheer/patronen/{patroon.id}"
    tekst = als_beheerder.post(url, data={
        "naam": patroon.naam, "weken": "3", "actie": "kopieer", "kopieer_van": "1",
        "kopieer_naar": ["2", "3"], **_raster(w1_0="4", w2_0="7", w3_0="5")}).data.decode()
    assert 'name="c-2-0" value="4"' in tekst and 'name="c-3-0" value="4"' in tekst
    antwoord = als_beheerder.post(url, data={
        "naam": patroon.naam, "weken": "3", "actie": "opslaan", **_raster(w1_0="4", w2_0="4", w3_0="4")})
    assert antwoord.status_code == 302
    db.session.expire_all()
    assert RoosterPatroon.query.one().cellen() == {(1, 0): "4", (2, 0): "4", (3, 0): "4"}


# ---------------------------------------------------------------------------
# Dienstcodes die in een patroon staan: niet hernummeren of verwijderen
# ---------------------------------------------------------------------------

def test_patronen_met_code(app, mw):
    _patroon("Vroeg", cellen={(1, 0): "4", (2, 0): "7"})
    _patroon("Tweede dienst", cellen={(1, 1): "/4", (2, 1): "5/17"})
    _patroon("Zonder 4", cellen={(1, 0): "14"})
    assert patronen.patronen_met_code(4) == ["Tweede dienst", "Vroeg"]
    assert patronen.patronen_met_code(17) == ["Tweede dienst"]
    assert patronen.patronen_met_code(1) == []  # '14' is niet code 1 of 4


def _code_formulier(code, **extra):
    return {"nummer": str(code.nummer), "omschrijving": code.omschrijving, "std_begin": code.std_begin,
            "std_eind": code.std_eind, "std_uren": str(code.std_uren), "vet": "1", "actief": "1",
            "in_agenda": "1", **extra}


def test_scherm_code_in_patroon_niet_hernummeren(app, als_beheerder, mw):
    from app.models import Dienstcode

    patroon = _patroon("Vroeg-laat", cellen={(1, 0): "4", (2, 0): "7"})
    code = Dienstcode.query.filter_by(nummer=4).one()
    antwoord = als_beheerder.post(f"/beheer/dienstcodes/{code.id}", data=_code_formulier(code, nummer="40"))
    tekst = antwoord.data.decode()
    assert antwoord.status_code == 400 and "Vroeg-laat" in tekst and "roosterpatroon" in tekst
    db.session.expire_all()
    assert Dienstcode.query.filter_by(nummer=4).one() and patroon.cellen()[(1, 0)] == "4"
    # Andere velden wijzigen en deactiveren mag wel
    antwoord = als_beheerder.post(f"/beheer/dienstcodes/{code.id}",
                                  data={**_code_formulier(code, omschrijving="VW Ochtend"), "actief": ""})
    assert antwoord.status_code == 302
    db.session.expire_all()
    code = Dienstcode.query.filter_by(nummer=4).one()
    assert code.omschrijving == "VW Ochtend" and not code.actief


def test_scherm_code_in_patroon_niet_verwijderen(app, als_beheerder, mw):
    from app.models import Dienstcode

    _patroon("Vroeg-laat", cellen={(1, 0): "4", (2, 0): "7"})
    _patroon("Alleen 2e dienst", cellen={(1, 0): "/4"})
    code = Dienstcode.query.filter_by(nummer=4).one()
    antwoord = als_beheerder.post(f"/beheer/dienstcodes/{code.id}/verwijder", follow_redirects=True)
    tekst = antwoord.data.decode()
    assert "Alleen 2e dienst, Vroeg-laat" in tekst and 'class="melding fout"' in tekst
    db.session.expire_all()
    assert Dienstcode.query.filter_by(nummer=4).one().actief  # niets veranderd
    # Een code die niet in een patroon staat, kan nog steeds weg
    vrij = Dienstcode.query.filter_by(nummer=5).one()
    als_beheerder.post(f"/beheer/dienstcodes/{vrij.id}/verwijder")
    assert Dienstcode.query.filter_by(nummer=5).first() is None


# ---------------------------------------------------------------------------
# Voorbeeld en resultaat: de inhoud mag intussen niet veranderd zijn (vingerafdruk)
# ---------------------------------------------------------------------------

VEROUDERD = "gewijzigd sinds het voorbeeld; controleer het bijgewerkte voorbeeld"


def test_vingerafdruk_patroon_en_bronweken(app, mw):
    patroon = _patroon()
    keuzes = _keuzes(patroon, [(mw[0].id, 1)], MAANDAG, MAANDAG + timedelta(days=13))
    afdruk = patronen.vingerafdruk(patroon)
    assert afdruk == patronen.vingerafdruk(patroon)
    patronen.sla_op(patroon, patroon.naam, 2, {(1, 0): "5", (2, 0): "7"})
    with pytest.raises(patronen.VoorbeeldVerouderd, match=VEROUDERD):
        patronen.pas_toe(patroon, keuzes, afdruk)
    assert Dienst.query.count() == 0
    assert patronen.pas_toe(patroon, keuzes, patronen.vingerafdruk(patroon))["nieuw"] == 2
    # Herhalen: de broncellen per medewerker
    a = mw[0]
    herhaal = _herhaal([a], MAANDAG + timedelta(weeks=8), MAANDAG + timedelta(weeks=9, days=-1))
    afdruk = patronen.herhaal_vingerafdruk(herhaal)
    assert wijzig_cellen([Wijziging(a.id, MAANDAG + timedelta(days=3), "code", "17")])[1] == []
    assert patronen.herhaal_vingerafdruk(herhaal) != afdruk
    with pytest.raises(patronen.VoorbeeldVerouderd):
        patronen.herhaal_pas_toe(herhaal, afdruk)
    assert Dienst.query.filter(Dienst.datum >= herhaal.van).count() == 0


def test_scherm_uitrollen_patroon_gewijzigd_na_voorbeeld(app, als_beheerder, mw):
    patroon = _patroon()
    url = f"/beheer/patronen/{patroon.id}/uitrollen"
    keuzes = {"mw": [mw[0].id], f"start-{mw[0].id}": "1", "van": "2026-W10", "tot_week": "2026-W11",
              "modus": "overschrijven", "feestdagen": "invullen"}
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    patronen.sla_op(patroon, patroon.naam, 2, {(1, 0): "5", (2, 0): "7"})  # intussen gewijzigd
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                                  follow_redirects=True)
    tekst = antwoord.data.decode()
    assert VEROUDERD in tekst and "Totaal: <strong>2</strong> nieuw" in tekst  # bijgewerkt voorbeeld
    assert Dienst.query.count() == 0
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"})
    assert antwoord.status_code == 302 and _code(mw[0], MAANDAG) == 5


def test_scherm_herhalen_bronweken_gewijzigd_na_voorbeeld(app, als_beheerder, mw):
    a = mw[0]
    _plan_acht_weken([a])
    url = "/beheer/patronen/herhalen"
    keuzes = {"mw": [a.id], "bron": "2026-W10", "weken": "8", "van": "2026-W18", "tot_week": "2026-W25",
              "modus": "overschrijven", "feestdagen": "invullen"}
    als_beheerder.post(url, data={**keuzes, "actie": "voorbeeld"}, follow_redirects=True)
    assert wijzig_cellen([Wijziging(a.id, MAANDAG + timedelta(days=3), "code", "17")])[1] == []
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"},
                                  follow_redirects=True)
    assert VEROUDERD in antwoord.data.decode() and "data-herhaal-uitleg" in antwoord.data.decode()
    assert Dienst.query.filter(Dienst.datum >= date(2026, 4, 27)).count() == 0
    antwoord = als_beheerder.post(url, data={**keuzes, "actie": "toepassen", "bevestig": "1"})
    assert antwoord.status_code == 302 and _cel(a, MAANDAG + timedelta(weeks=8, days=3)) == "17"


# ---------------------------------------------------------------------------
# Rooster herhalen: collega's zonder diensten in de bronweken
# ---------------------------------------------------------------------------

GEWIST = "geen diensten in de bronweken: in de doelperiode wordt alles gewist"


def test_herhalen_waarschuwt_bij_medewerker_zonder_bronrooster(app, mw):
    a, b, _ = mw
    _plan_acht_weken([a])
    doel = MAANDAG + timedelta(weeks=8)
    assert wijzig_cellen([Wijziging(b.id, doel, "code", "5")])[1] == []  # B: alleen een dienst in het doel
    keuzes = _herhaal([a, b], doel, doel + timedelta(weeks=8, days=-1))
    effect = patronen.herhaal_effect(keuzes)
    assert effect.waarschuwingen == [f"Medewerker B: {GEWIST}."]
    assert effect.per_medewerker[b.id].verwijderd == 1
    # Bij aanvullen wordt niets gewist: geen waarschuwing
    aanvullen = _herhaal([a, b], doel, doel + timedelta(weeks=8, days=-1), modus=patronen.MODUS_AANVULLEN)
    assert patronen.herhaal_effect(aanvullen).waarschuwingen == []


def test_scherm_herhalen_standaard_alleen_medewerkers_met_bronrooster(app, als_beheerder, mw, monkeypatch):
    from app.services import klok

    a, b, c = mw
    monkeypatch.setattr(klok, "vandaag", lambda: MAANDAG + timedelta(days=2))  # standaard bronweek: week 10
    _plan_acht_weken([a, c])
    c.gearchiveerd_vanaf = MAANDAG + timedelta(weeks=8)  # vóór de standaard startweek
    assert wijzig_cellen([Wijziging(b.id, MAANDAG, "opmerking", "Alleen een opmerking")])[1] == []
    db.session.commit()
    pagina = als_beheerder.get("/beheer/patronen/herhalen").data.decode()
    assert 'name="bron" value="2026-W10"' in pagina
    assert f'value="{a.id}" checked' in pagina  # diensten in de bronweken
    assert f'value="{b.id}" checked' not in pagina  # alleen een opmerking: geen dienst
    assert f'value="{c.id}" checked' not in pagina  # gearchiveerd
    # Kies je B toch, dan waarschuwt het voorbeeld
    als_beheerder.post("/beheer/patronen/herhalen", data={
        "mw": [a.id, b.id], "bron": "2026-W10", "weken": "8", "van": "2026-W18", "tot_week": "2026-W25",
        "modus": "overschrijven", "feestdagen": "invullen", "actie": "voorbeeld"})
    tekst = als_beheerder.get("/beheer/patronen/herhalen").data.decode()
    assert f"Medewerker B: {GEWIST}." in tekst and f'value="{b.id}" checked' in tekst
