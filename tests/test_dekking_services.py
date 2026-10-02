"""Services: back-up, Google-synchronisatie en weekrooster in zeldzame situaties. Data is fictief."""

import os
import sqlite3
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Dagopmerking, Dienst, Medewerker, SyncTaak
from app.services import backup, sync, sync_planning, weekrooster
from app.services.google_agenda import AgendaFout, afspraak_voor
from app.services.voorbeeldpakket import laad_voorbeeldpakket
from app.services.weekrooster import (
    VersieConflict,
    Wijziging,
    kopieer_week,
    pas_dagopmerking_toe,
    wijzig_cellen,
)

from .test_agenda import NepKlant, gekoppeld, nep  # noqa: F401  (fixtures)

MAANDAG = date(2026, 3, 2)


# ---------------------------------------------------------------------------
# Back-ups
# ---------------------------------------------------------------------------

def test_backups_alleen_met_sqlite(app):
    oud = app.config["SQLALCHEMY_DATABASE_URI"]
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://iemand@server/db"
    try:
        with pytest.raises(RuntimeError, match="alleen met SQLite"):
            backup.database_pad()
    finally:
        app.config["SQLALCHEMY_DATABASE_URI"] = oud


def test_kopie_die_de_controle_niet_haalt(app, monkeypatch):
    class NepVerbinding:
        def execute(self, _sql):
            return self

        def fetchone(self):
            return ("*** in database main ***",)

        def close(self):
            pass

    monkeypatch.setattr(backup.sqlite3, "connect", lambda _pad: NepVerbinding())
    with pytest.raises(sqlite3.DatabaseError, match="niet in orde"):
        backup._controleer_kopie("x.db")


def test_backup_mislukt_voordat_er_een_bestand_is(app, monkeypatch):
    def kapot(_pad):
        raise sqlite3.OperationalError("geen toegang")

    monkeypatch.setattr(backup.sqlite3, "connect", kapot)
    with pytest.raises(sqlite3.OperationalError):
        backup.maak_backup("handmatig")
    assert os.listdir(backup.backup_map()) == []


def test_lijst_negeert_andere_bestanden_en_jonge_gelabelde_blijven(app):
    with open(os.path.join(backup.backup_map(), "leesmij.txt"), "w") as bestand:
        bestand.write("geen back-up")
    for i in range(12):  # meer dan GELABELD_MINIMAAL, maar allemaal van vandaag
        backup.maak_backup(f"handmatig{i}")
    assert all(b["naam"] != "leesmij.txt" for b in backup.lijst_backups())
    assert backup.ruim_gelabelde_op() == 0


@pytest.mark.parametrize("sql, melding", [
    ("CREATE TABLE medewerker (id INTEGER); CREATE TABLE dienst (id INTEGER);", "geen back-up van"),
    ("CREATE TABLE medewerker (id INTEGER); CREATE TABLE dienst (id INTEGER);"
     "CREATE TABLE alembic_version (version_num TEXT);", "geen databaseversie"),
])
def test_backupbestand_controle(tmp_path, sql, melding):
    pad = str(tmp_path / "test.db")
    verbinding = sqlite3.connect(pad)
    verbinding.executescript(sql)
    verbinding.close()
    with pytest.raises(ValueError, match=melding):
        backup.controleer_backupbestand(pad)


# ---------------------------------------------------------------------------
# Google-synchronisatie
# ---------------------------------------------------------------------------

def _dienst(medewerker, **extra):
    dienst = Dienst(medewerker_id=medewerker.id, datum=MAANDAG, versie=1, **extra)
    db.session.add(dienst)
    db.session.commit()
    return dienst


def test_zet_afspraak_zonder_gewenste_en_zonder_bestaande(app, gekoppeld, nep):  # noqa: F811
    dienst = _dienst(gekoppeld)
    sync._zet_afspraak(nep, "agenda-a", dienst, None, "")
    assert dienst.google_event_id == ""


def test_zet_afspraak_andere_fout_wordt_doorgegeven(app, gekoppeld):  # noqa: F811
    class Kapot(NepKlant):
        def wijzig_afspraak(self, agenda_id, event_id, body):
            raise AgendaFout("Google stuk (500)", status=500)

    dienst = _dienst(gekoppeld, dienstnaam_override="Cursus", begin="08:00", eind="12:00")
    with pytest.raises(AgendaFout, match="500"):
        sync._zet_afspraak(Kapot(), "agenda-a", dienst, afspraak_voor(dienst, ""), "bestaand-1")


def test_volledige_sync_met_dienst_zonder_afspraak(app, gekoppeld, nep):  # noqa: F811
    _dienst(gekoppeld, opmerking_tekst="Alleen een opmerking")
    assert sync.sync_volledig(nep, gekoppeld) == 0


def test_ontkoppelen_randgevallen(app, gekoppeld, nep):  # noqa: F811
    sync.ontkoppel(nep, {"verwijder": False, "agenda_id": "agenda-a"})
    sync.ontkoppel(nep, {"verwijder": True, "agenda_id": ""})
    sync.ontkoppel(nep, {"verwijder": True, "agenda_id": "agenda-a", "modus": "B"})  # zonder medewerker
    assert "agenda-a" in nep.agendas
    sync.ontkoppel(nep, {"verwijder": True, "agenda_id": "bestaat-niet", "modus": "A"})

    class Kapot(NepKlant):
        def verwijder_agenda(self, agenda_id):
            raise AgendaFout("niet gevonden", status=404) if agenda_id == "weg" else \
                AgendaFout("stuk", status=500)

    sync.ontkoppel(Kapot(), {"verwijder": True, "agenda_id": "weg", "modus": "A"})  # 404: al weg
    with pytest.raises(AgendaFout, match="stuk"):
        sync.ontkoppel(Kapot(), {"verwijder": True, "agenda_id": "agenda-x", "modus": "A"})


def test_taak_voor_ontkoppelde_medewerker_doet_niets(app, klaar, nep):  # noqa: F811
    medewerker = Medewerker(naam="Medewerker Z", initialen="MZ")
    db.session.add(medewerker)
    db.session.flush()
    db.session.add(SyncTaak(medewerker_id=medewerker.id, datum=MAANDAG, soort="dag",
                            niet_voor=date(2000, 1, 1)))
    db.session.commit()
    assert sync.verwerk_wachtrij(lambda: nep) == 1
    assert SyncTaak.query.count() == 0


def test_taak_die_een_ander_al_pakte_wordt_overgeslagen(app, gekoppeld, nep, monkeypatch):  # noqa: F811
    db.session.add(SyncTaak(medewerker_id=gekoppeld.id, datum=MAANDAG, soort="dag",
                            niet_voor=date(2000, 1, 1)))
    db.session.commit()
    monkeypatch.setattr(sync, "_claim", lambda _taak_id: None)
    assert sync.verwerk_wachtrij(lambda: nep) == 0


def test_planning_toekomst_volledig_en_ontkoppelen(app, gekoppeld, monkeypatch):  # noqa: F811
    from app.services import klok

    monkeypatch.setattr(klok, "vandaag", lambda: MAANDAG)
    _dienst(gekoppeld, dienstnaam_override="Cursus", begin="08:00", eind="12:00")
    sync_planning.plan_toekomst(gekoppeld)
    assert SyncTaak.query.filter_by(soort="dag").count() == 1
    sync_planning.plan_volledig(gekoppeld)
    sync_planning.plan_volledig(gekoppeld)  # tweede keer: geen dubbele taak
    assert SyncTaak.query.filter_by(soort="volledig").count() == 1
    leeg = Dienst(medewerker_id=gekoppeld.id, datum=MAANDAG + timedelta(days=1), versie=1,
                  google_event_id="afspraak-oud")
    db.session.add(leeg)
    db.session.commit()
    sync_planning.plan_ontkoppel(gekoppeld, verwijder=False)
    db.session.commit()
    assert SyncTaak.query.filter_by(soort="ontkoppel").count() == 0
    assert Dienst.query.filter_by(datum=MAANDAG + timedelta(days=1)).first() is None  # lege regel weg


# ---------------------------------------------------------------------------
# Weekrooster
# ---------------------------------------------------------------------------

@pytest.fixture
def mw(klaar):
    laad_voorbeeldpakket()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.commit()
    return medewerker


def test_dagopmerking_wijzigen_en_niets_veranderd(app, mw):
    pas_dagopmerking_toe(MAANDAG, "")  # geen automatische tekst en niets handmatigs: niets te doen
    assert Dagopmerking.query.count() == 0
    pas_dagopmerking_toe(MAANDAG, "Eerste")
    pas_dagopmerking_toe(MAANDAG, "Tweede")
    db.session.commit()
    assert Dagopmerking.query.one().tekst == "Tweede"


def test_uren_veld_en_foute_invoer(app, mw):
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4"),
                          Wijziging(mw.id, MAANDAG, "uren", "9")])[1] == []
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "uren", "")])[1] == []
    assert Dienst.query.one().uren_handmatig is None
    fouten = wijzig_cellen([Wijziging(mw.id, MAANDAG, "uren", "30"), Wijziging(mw.id, MAANDAG, "kleur", "x"),
                            Wijziging(99999, MAANDAG, "code", "4")])[1]
    meldingen = " ".join(f["melding"] for f in fouten)
    assert "tussen 0 en 24" in meldingen and "Onbekend veld" in meldingen
    assert "Onbekende medewerker" in meldingen


def test_tweede_dienst_erbij_na_wijziging_van_dienst_1(app, mw):
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4"),
                          Wijziging(mw.id, MAANDAG, "uren", "9")])[1] == []
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "opmerking", "Locatie A"),
                          Wijziging(mw.id, MAANDAG, "code", "7", volgnummer=2)])[1] == []
    dienst1 = Dienst.query.filter_by(volgnummer=1).one()
    assert dienst1.uren_handmatig is None and dienst1.opmerking_tekst == "Locatie A"


def test_gelijktijdig_aangemaakt_wordt_versieconflict(app, mw, monkeypatch):
    def botsing(_wijzigingen):
        raise IntegrityError("INSERT", {}, Exception("UNIQUE"))

    monkeypatch.setattr(weekrooster, "_pas_cellen_toe", botsing)
    with pytest.raises(VersieConflict):
        weekrooster.verwerk_rooster([Wijziging(mw.id, MAANDAG, "code", "4")])


def test_week_kopieren_naar_zichzelf_en_al_gelijk(app, mw):
    assert kopieer_week(MAANDAG, MAANDAG) == 0
    assert wijzig_cellen([Wijziging(mw.id, MAANDAG, "code", "4")])[1] == []
    kopieer_week(MAANDAG, MAANDAG + timedelta(weeks=1))
    from app.models import Logboek
    regels = Logboek.query.filter_by(actie="Rooster gewijzigd").count()
    kopieer_week(MAANDAG, MAANDAG + timedelta(weeks=1))  # al gelijk: geen nieuwe logregel
    assert Logboek.query.filter_by(actie="Rooster gewijzigd").count() == regels
