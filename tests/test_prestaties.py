"""Prestaties: het weekrooster met 15 medewerkers en een vol jaar aan diensten.

Eis: de pagina laadt binnen 300 ms, en het aantal databasequery's hangt niet af van
het aantal medewerkers (geen N+1).
"""

import gc
import time
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models import Contracturen, Dienst, Dienstcode, Medewerker, OpmerkingKleurregel

MAX_MS = 300


def _vul(aantal_medewerkers: int) -> None:
    """Medewerkers met contracturen en voor elke dag van 2026 een dienst."""
    codes = []
    for nummer in range(1, 11):
        code = Dienstcode(nummer=nummer, omschrijving=f"Dienst {nummer}", std_begin="07:00",
                          std_eind="15:00", std_uren=7.5)
        db.session.add(code)
        codes.append(code)
    db.session.add(OpmerkingKleurregel(tekst="Locatie A", kleur_achtergrond="#00FF00"))
    db.session.flush()
    eerste = date(2026, 1, 1)
    for i in range(aantal_medewerkers):
        medewerker = Medewerker(naam=f"Medewerker {i:02d}", initialen=f"M{i:02d}", volgorde=i)
        db.session.add(medewerker)
        db.session.flush()
        db.session.add_all([Contracturen(medewerker_id=medewerker.id, jaar=2025, uren=1400),
                            Contracturen(medewerker_id=medewerker.id, jaar=2026, uren=1500)])
        db.session.add_all([
            Dienst(medewerker_id=medewerker.id, datum=eerste + timedelta(days=d),
                   dienstcode_id=codes[(i + d) % 10].id, begin="07:00", eind="15:00",
                   uren_berekend=7.5, opmerking_tekst="Locatie A" if d % 3 == 0 else "")
            for d in range(365)
        ])
    db.session.commit()


class Teller:
    """Telt de SQL-query's tijdens een verzoek."""

    def __init__(self) -> None:
        self.aantal = 0

    def __call__(self, *args, **kwargs) -> None:
        self.aantal += 1


def _meet(client, url: str) -> tuple[float, int]:
    teller = Teller()
    event.listen(db.engine, "before_cursor_execute", teller)
    try:
        start = time.perf_counter()
        antwoord = client.get(url)
        duur = (time.perf_counter() - start) * 1000
    finally:
        event.remove(db.engine, "before_cursor_execute", teller)
    assert antwoord.status_code == 200
    return duur, teller.aantal


@pytest.mark.parametrize("rol", ["beheerder", "collega"])
def test_weekrooster_15_medewerkers_vol_jaar_binnen_300ms(app, klaar, rol):
    from .conftest import login

    _vul(15)
    client = app.test_client()
    login(client, rol)
    client.get("/week/2026/23")  # eerste keer: templates compileren
    db.session.expire_all()
    duren = []
    for _ in range(3):
        duur, _aantal = _meet(client, "/week/2026/23")
        duren.append(duur)
        db.session.expire_all()
    beste = min(duren)
    print(f"\nWeekrooster ({rol}, 15 medewerkers, 5475 diensten): {beste:.0f} ms")
    assert beste < MAX_MS, f"weekrooster laadt in {beste:.0f} ms (eis: < {MAX_MS} ms)"


def test_weekrooster_geen_n_plus_1(app, klaar):
    from .conftest import login

    client = app.test_client()
    login(client, "beheerder")
    _vul(3)
    client.get("/week/2026/23")
    db.session.expire_all()
    _duur, weinig = _meet(client, "/week/2026/23")

    # 12 medewerkers erbij: het aantal query's mag niet groeien
    for i in range(3, 15):
        medewerker = Medewerker(naam=f"Extra {i}", initialen=f"E{i}", volgorde=i)
        db.session.add(medewerker)
        db.session.flush()
        db.session.add(Contracturen(medewerker_id=medewerker.id, jaar=2026, uren=1500))
        db.session.add(Dienst(medewerker_id=medewerker.id, datum=date(2026, 6, 2),
                              dienstcode_id=Dienstcode.query.first().id, begin="07:00",
                              eind="15:00", uren_berekend=7.5))
    db.session.commit()
    db.session.expire_all()
    _duur, veel = _meet(client, "/week/2026/23")
    assert veel == weinig, f"{weinig} query's met 3 medewerkers, {veel} met 15 (N+1)"


def test_urenoverzicht_geen_n_plus_1(app, klaar):
    """Contracturen per medewerker mogen geen extra query per medewerker kosten (audit 1.4.4)."""
    from .conftest import login

    client = app.test_client()
    login(client, "beheerder")
    _vul(3)
    client.get("/overzicht/uren?jaar=2026")
    db.session.expire_all()
    _duur, weinig = _meet(client, "/overzicht/uren?jaar=2026")
    for i in range(3, 15):
        medewerker = Medewerker(naam=f"Extra {i}", initialen=f"E{i}", volgorde=i)
        db.session.add(medewerker)
        db.session.flush()
        db.session.add(Contracturen(medewerker_id=medewerker.id, jaar=2026, uren=1500))
    db.session.commit()
    db.session.expire_all()
    _duur, veel = _meet(client, "/overzicht/uren?jaar=2026")
    assert veel == weinig, f"{weinig} query's met 3 medewerkers, {veel} met 15 (N+1)"


MAX_EXPORT_S = 5  # 'binnen een paar seconden'


@contextmanager
def zonder_coverage():
    """Meet de app, niet de coverage-meting van CI (die maakt Python ruim twee keer zo traag).

    De export zelf wordt elders in de suite wel onder coverage getest.
    Ook ruimen we vooraf het geheugen op en 'bevriezen' we wat eerdere tests achterlieten
    (gc.freeze): de formule-tests laten ruim een miljoen objecten van de bibliotheek
    'formulas' achter, en elke garbage collection tijdens de meting liep die anders na.
    """
    try:
        import coverage

        actief = coverage.Coverage.current()
    except ImportError:  # coverage niet geïnstalleerd
        actief = None
    if actief is not None:
        actief.stop()
    gc.collect()
    gc.freeze()
    try:
        yield
    finally:
        gc.unfreeze()
        if actief is not None:
            actief.start()


def test_excel_export_15_medewerkers_vol_jaar(app, klaar):
    """Excel-export van een jaar met 15 medewerkers (5475 diensten) binnen een paar seconden."""
    from .conftest import login

    _vul(15)
    client = app.test_client()
    login(client, "beheerder")  # sinds 1.6.0 alleen voor de beheerder, mét formules
    with zonder_coverage():
        start = time.perf_counter()
        antwoord = client.get("/beheer/exporteren/rooster.xlsx?soort=jaar&jaar=2026")
        duur = time.perf_counter() - start
    assert antwoord.status_code == 200 and len(antwoord.data) > 10_000
    print(f"\nExcel-export (15 medewerkers, 5475 diensten): {duur:.2f} s")
    assert duur < MAX_EXPORT_S, f"export duurt {duur:.1f} s (eis: < {MAX_EXPORT_S} s)"
