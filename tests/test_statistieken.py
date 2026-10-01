"""Beheer → Statistieken (Deel 3, versie 1.6.0): alleen-lezen overzicht voor de planner."""

import os
from datetime import date, datetime, timedelta

import pytest

from app.extensions import db
from app.models import ApiToken, Dienst, Dienstcode, Logboek, LoginPoging, Medewerker, SyncTaak
from app.services import backup, klok, statistieken
from app.services.voorbeeldpakket import laad_voorbeeldpakket

from .test_prestaties import Teller


@pytest.fixture
def gegevens(klaar):
    laad_voorbeeldpakket()
    a = Medewerker(naam="Medewerker A", initialen="MA", volgorde=1, agenda_modus="B", agenda_id="x",
                   agenda_laatste_fout="403: geen toegang tot de agenda",
                   agenda_laatst_gesync=datetime(2026, 9, 30, 12, 0))
    b = Medewerker(naam="Medewerker B", initialen="MB", volgorde=2)
    db.session.add_all([a, b])
    db.session.commit()
    return {"a": a, "b": b}


def _backup(naam: str, dagen_geleden: float = 0, grootte: int = 100) -> None:
    pad = os.path.join(backup.backup_map(), naam)
    with open(pad, "wb") as bestand:
        bestand.write(b"x" * grootte)
    tijd = (klok.nu() - timedelta(days=dagen_geleden)).timestamp()
    os.utime(pad, (tijd, tijd))


def _stempel(dagen_geleden: float) -> str:
    return (klok.nu() - timedelta(days=dagen_geleden)).strftime("%Y%m%d-%H%M%S")


def test_agenda_fouten_en_wachtrij(app, gegevens):
    nu = klok.utc_nu()
    db.session.add_all([
        SyncTaak(medewerker_id=gegevens["a"].id, soort="dag", status="wacht",
                 aangemaakt_op=datetime(2026, 9, 1, 8, 0)),
        SyncTaak(medewerker_id=gegevens["a"].id, soort="dag", status="wacht",
                 aangemaakt_op=datetime(2026, 9, 2, 8, 0)),
        SyncTaak(medewerker_id=gegevens["a"].id, soort="volledig", status="fout", laatste_fout="500",
                 niet_voor=nu),
        SyncTaak(medewerker_id=None, soort="ontkoppel", status="bezig", niet_voor=nu),
    ])
    db.session.commit()
    s = statistieken.verzamel()
    assert [(m.naam, m.agenda_laatste_fout) for m in s.agenda.fouten] == [
        ("Medewerker A", "403: geen toegang tot de agenda")]
    assert s.agenda.wachtrij == {"wacht": 2, "bezig": 1, "fout": 1}
    assert s.agenda.oudste_wachtend.aangemaakt_op == datetime(2026, 9, 1, 8, 0)
    assert s.meldingen and "Google Agenda" in s.meldingen[0]


def test_backups(app, klaar):
    drie_dagen = f"rooster-{_stempel(3)}.db"
    _backup(drie_dagen, 3)
    _backup(f"rooster-{_stempel(5)}.db", 5, grootte=300)
    _backup(f"rooster-{_stempel(1)}.db", 1, grootte=0)  # mislukt (leeg): telt niet
    _backup(f"rooster-{_stempel(0.5)}-voor-import.db", 0.5, grootte=50)
    db.session.add(Logboek(actie="Back-up mislukt", details="OSError: schijf vol", gebruiker="systeem"))
    db.session.commit()
    s = statistieken.verzamel().backups
    assert s.laatste_automatisch["naam"] == drie_dagen
    assert s.laatste_label["naam"].endswith("-voor-import.db")
    assert (s.aantal, s.totale_grootte) == (3, 450)
    assert s.te_oud and s.laatste_mislukt.details == "OSError: schijf vol"
    assert any("back-up" in m.lower() for m in statistieken.verzamel().meldingen)


def test_recente_backup_geeft_geen_waarschuwing(app, klaar):
    _backup(f"rooster-{_stempel(1)}.db", 1)
    s = statistieken.verzamel()
    assert not s.backups.te_oud and s.meldingen == []


def test_zonder_backups_wel_een_waarschuwing(app, klaar):
    s = statistieken.verzamel().backups
    assert s.laatste_automatisch is None and s.te_oud and s.aantal == 0


def test_rooster(app, gegevens, monkeypatch):
    monkeypatch.setattr(klok, "vandaag", lambda: date(2026, 3, 11))  # woensdag week 11
    from app.models import Contracturen
    from app.services.weekrooster import Wijziging, wijzig_cellen

    a, b = gegevens["a"], gegevens["b"]
    db.session.add(Contracturen(medewerker_id=a.id, jaar=2026, uren=1664))  # 32 uur per week
    db.session.commit()
    maandag = date(2026, 3, 2)
    assert wijzig_cellen([
        Wijziging(a.id, maandag, "code", "4"),
        Wijziging(a.id, maandag + timedelta(days=1), "code", "4"),
        Wijziging(a.id, maandag + timedelta(days=1), "eind", "17:00"),  # afwijkende tijd
        Wijziging(b.id, maandag, "code", "4"), Wijziging(b.id, maandag, "uren", "6"),  # zelf ingevuld
        Wijziging(a.id, date(2026, 6, 1), "code", "4"),  # later in het jaar (nog niet gewerkt)
    ])[1] == []
    # Een dag met dienst 2 én zelf ingevulde uren bij dienst 1 (van vóór de bugfix in 1.6.0)
    db.session.add(Dienst(medewerker_id=b.id, datum=maandag + timedelta(days=2), volgnummer=1,
                          dienstcode_id=Dienstcode.query.filter_by(nummer=4).one().id, begin="07:15",
                          eind="13:00", uren_handmatig=9.25,
                          uren_berekend=9.25))
    db.session.add(Dienst(medewerker_id=b.id, datum=maandag + timedelta(days=2), volgnummer=2,
                          dienstnaam_override="Training", begin="13:00", eind="17:00", uren_berekend=4))
    db.session.commit()
    s = statistieken.verzamel().rooster
    assert s.jaar == 2026 and s.aantal_diensten == 6
    rij_a = next(r for r in s.uren if r.medewerker.id == a.id)
    assert rij_a.gewerkt == 8 + 9.25 and rij_a.gepland == 8 + 9.25 + 8
    assert rij_a.contract_tot_nu == pytest.approx(1664 * 11 / 53)
    assert {(d.medewerker.naam, d.datum) for d in s.handmatige_uren} == {
        ("Medewerker B", maandag), ("Medewerker B", maandag + timedelta(days=2))}
    assert [(d.medewerker.naam, d.datum) for d in s.afwijkende_tijden] == [
        ("Medewerker A", maandag + timedelta(days=1))]
    assert [(d.medewerker.naam, d.datum) for d in s.mogelijk_dubbel] == [
        ("Medewerker B", maandag + timedelta(days=2))]


def test_beveiliging(app, klaar):
    nu = klok.utc_nu()
    db.session.add_all([
        LoginPoging(gebruikersnaam="onbekend", ip="10.0.0.1", tijdstip=nu - timedelta(hours=1)),
        LoginPoging(gebruikersnaam="onbekend", ip="10.0.0.1", tijdstip=nu - timedelta(hours=2)),
        LoginPoging(gebruikersnaam="collega", ip="10.0.0.2", tijdstip=nu - timedelta(hours=3)),
        LoginPoging(gebruikersnaam="collega", ip="10.0.0.2", tijdstip=nu - timedelta(hours=30)),  # te oud
        LoginPoging(gebruikersnaam="collega", ip="10.0.0.2", tijdstip=nu, gelukt=True),
        Logboek(actie="Login geblokkeerd", details="IP 10.0.0.1", gebruiker="onbekend",
                tijdstempel=klok.nu() - timedelta(hours=1)),
        Logboek(actie="Login geblokkeerd", details="oud", gebruiker="x",
                tijdstempel=klok.nu() - timedelta(days=2)),
    ])
    gebruiker = klaar["beheerder"]
    db.session.add_all([
        ApiToken(gebruiker_id=gebruiker.id, naam="Telefoon", token_hash="a" * 64, prefix="br_aaaa",
                 sessie_sleutel=gebruiker.get_id(), verloopt_op=nu + timedelta(days=30)),
        ApiToken(gebruiker_id=gebruiker.id, naam="Verlopen", token_hash="b" * 64, prefix="br_bbbb",
                 sessie_sleutel=gebruiker.get_id(), verloopt_op=nu - timedelta(days=1)),
        ApiToken(gebruiker_id=gebruiker.id, naam="Oud wachtwoord", token_hash="c" * 64, prefix="br_cccc",
                 sessie_sleutel="1:0:oud", verloopt_op=nu + timedelta(days=30)),
    ])
    db.session.commit()
    s = statistieken.verzamel().beveiliging
    assert s.mislukte_pogingen == 3
    assert s.per_bron[:2] == [("onbekend", "10.0.0.1", 2), ("collega", "10.0.0.2", 1)]
    assert [r.details for r in s.blokkades] == ["IP 10.0.0.1"]
    assert [t.naam for t in s.actieve_tokens] == ["Telefoon"]


def test_scherm_alleen_beheerder(app, client, gegevens):
    from .conftest import login

    login(client, "collega")
    assert client.get("/beheer/statistieken").status_code == 403


def test_scherm_toont_alles(app, als_beheerder, gegevens):
    db.session.add(SyncTaak(medewerker_id=gegevens["a"].id, status="fout", laatste_fout="500"))
    db.session.commit()
    tekst = als_beheerder.get("/beheer/statistieken").data.decode()
    for kop in ("Google Agenda", "Back-ups", "Rooster", "Beveiliging"):
        assert f"<h2>{kop}" in tekst, kop
    assert "403: geen toegang tot de agenda" in tekst and "Mislukte opnieuw proberen" in tekst
    assert 'href="/beheer/agenda"' in tekst and "Er is nog geen automatische back-up" in tekst
    index = als_beheerder.get("/beheer/").data.decode()
    assert "Statistieken" in index and "data-beheer-melding" in index
    assert "Google Agenda" in index


def test_beheer_startpagina_zonder_problemen_geen_melding(app, als_beheerder):
    _backup(f"rooster-{_stempel(0.2)}.db", 0.2)
    assert "data-beheer-melding" not in als_beheerder.get("/beheer/").data.decode()


def test_geen_n_plus_1(app, als_beheerder, gegevens):
    from app.services.weekrooster import Wijziging, wijzig_cellen

    def meet():
        teller = Teller()
        from sqlalchemy import event

        db.session.expire_all()
        event.listen(db.engine, "before_cursor_execute", teller)
        try:
            assert als_beheerder.get("/beheer/statistieken").status_code == 200
        finally:
            event.remove(db.engine, "before_cursor_execute", teller)
        return teller.aantal

    vandaag = klok.vandaag()
    wijzig_cellen([Wijziging(gegevens["a"].id, vandaag, "uren", "5")])
    meet()
    weinig = meet()
    for i in range(12):
        m = Medewerker(naam=f"Extra {i}", initialen=f"E{i}", agenda_modus="B", agenda_id="x",
                       agenda_laatste_fout="fout")
        db.session.add(m)
        db.session.flush()
        db.session.add(SyncTaak(medewerker_id=m.id, status="wacht"))
    db.session.commit()
    wijzig_cellen([Wijziging(m.id, vandaag, "uren", "5") for m in Medewerker.query.all()])
    assert meet() == weinig
