"""Regressietests voor de bevindingen uit de audit van versie 1.4.4.

Elke test hoort bij één bevinding (H = high, M = medium, L = low, S = security).
De test faalde op de oude code en slaagt na de reparatie.
"""

from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import Dienst, Medewerker, SyncTaak

MAANDAG = date(2026, 3, 2)  # week 10 van 2026


@pytest.fixture
def mw(klaar):
    from app.services.voorbeeldpakket import laad_voorbeeldpakket

    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1)
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def _import_dienst(naam, dag, **extra):
    from app.services.excel_import import ImportDienst

    waarden = dict(naam=naam, datum=dag, code=None, dienstnaam="Cursus", begin="08:00",
                   eind="16:00", opmerking="", opm_begin=None, opm_eind=None, excel_uren=None)
    waarden.update(extra)
    return ImportDienst(**waarden)


def _wachtrij_nu():
    from app.services import sync

    SyncTaak.query.update({"niet_voor": datetime(2000, 1, 1)})
    db.session.commit()
    return sync.verwerk_wachtrij()


# ---------------------------------------------------------------------------
# H1 · De Excel-import wist diensten in weken die niet in het bestand staan
# ---------------------------------------------------------------------------

def test_h1_import_laat_weken_zonder_blad_ongemoeid(app, mw):
    from app.services.excel_import import ImportMedewerker, ImportPlan, importeer

    week12 = MAANDAG + timedelta(weeks=2)
    db.session.add(Dienst(medewerker_id=mw.id, datum=week12, dienstnaam_override="Blijft",
                          begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()
    plan = ImportPlan(jaar=2026, weken=[10, 14],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", MAANDAG),
                                _import_dienst("Medewerker A", MAANDAG + timedelta(weeks=4))])
    importeer(plan)
    assert Dienst.query.filter_by(datum=week12).one().dienstnaam_override == "Blijft"
    assert Dienst.query.count() == 3


def test_h1_droogloop_toont_te_verwijderen_bestaande_diensten(app, mw):
    from app.services.excel_import import ImportMedewerker, ImportPlan, effect

    for dag in (MAANDAG, MAANDAG + timedelta(days=1), MAANDAG + timedelta(weeks=2)):
        db.session.add(Dienst(medewerker_id=mw.id, datum=dag, dienstnaam_override="Oud",
                              begin="07:00", eind="15:00", opmerking_tekst=""))
    db.session.commit()
    plan = ImportPlan(jaar=2026, weken=[10],
                      medewerkers=[ImportMedewerker("Medewerker A", "MA", None)],
                      diensten=[_import_dienst("Medewerker A", MAANDAG)])
    per_mw = effect(plan).per_medewerker["Medewerker A"]
    # Maandag wordt vervangen, dinsdag verwijderd; week 12 (geen blad) telt niet mee
    assert (per_mw.nieuw, per_mw.vervangen, per_mw.verwijderd) == (0, 1, 1)


def test_h1_droogloopscherm_toont_verwijderde_diensten_per_medewerker(app, als_beheerder, tmp_path):
    import io

    from .test_import_backup import maak_testbestand

    medewerker = Medewerker(naam="Medewerker Vijf B", initialen="MVB")
    db.session.add(medewerker)
    db.session.commit()
    for dag in (MAANDAG + timedelta(days=1), MAANDAG + timedelta(days=2)):  # niet in het bestand
        db.session.add(Dienst(medewerker_id=medewerker.id, datum=dag, dienstnaam_override="Oud",
                              opmerking_tekst=""))
    db.session.commit()
    pad = str(tmp_path / "oud.xlsx")
    maak_testbestand(pad)
    with open(pad, "rb") as f:
        als_beheerder.post("/beheer/importeren", data={"bestand": (io.BytesIO(f.read()), "x.xlsx")},
                           content_type="multipart/form-data")
    pagina = als_beheerder.get("/beheer/importeren/voorbeeld").data.decode()
    rij = pagina.split("data-effect")[1].split("Medewerker Vijf B")[1].split("</tr>")[0]
    assert "<strong>2</strong>" in rij
