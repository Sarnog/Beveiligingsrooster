"""Bijwerken vanaf 1.1.2 (databaseversie 0003) naar de nieuwste versie, met echte (fictieve) data.

De database wordt gevuld met SQL zoals 1.1.2 hem schreef, daarna gemigreerd. Alles moet
intact blijven en bestaande gebruikers moeten opnieuw inloggen (nieuw sessieformaat).
"""

import os
from datetime import date

import pytest
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.services.wachtwoorden import hash_wachtwoord

from . import conftest
from .conftest import WACHTWOORD, login

MIGRATIES = os.path.join(os.path.dirname(__file__), "..", "migrations")


def _sql(verbinding, opdracht: str, *waarden) -> None:
    verbinding.exec_driver_sql(opdracht, tuple(waarden))


def _vul_versie_112(verbinding) -> None:
    """Data zoals die in een database van versie 1.1.2 (revisie 0003) stond."""
    _sql(verbinding, "INSERT INTO instelling (sleutel, waarde) VALUES ('setup_voltooid', '1')")
    _sql(verbinding, "INSERT INTO instelling (sleutel, waarde) VALUES ('teamnaam', 'Team Fictief')")
    _sql(verbinding, "INSERT INTO dienstcode (id, nummer, omschrijving, std_begin, std_eind, std_uren, "
         "kleur_achtergrond, kleur_tekst, vet, cursief, in_agenda, hele_dag_zonder_tijden, actief) "
         "VALUES (1, 4, 'Dagdienst', '07:00', '15:00', 7.5, '#ffff00', '#000000', 0, 0, 1, 0, 1)")
    _sql(verbinding, "INSERT INTO dienstcode (id, nummer, omschrijving, std_begin, std_eind, std_uren, "
         "kleur_achtergrond, kleur_tekst, vet, cursief, in_agenda, hele_dag_zonder_tijden, actief) "
         "VALUES (2, 9, 'Vrij', NULL, NULL, NULL, '#ffffff', '#000000', 0, 0, 0, 1, 1)")
    for nummer in (1, 2, 3):
        _sql(verbinding, "INSERT INTO medewerker (id, naam, initialen, functie_opmerking, volgorde, email, "
             "gearchiveerd_vanaf, agenda_modus, agenda_id, agenda_laatst_gesync, agenda_laatste_fout, "
             "ics_token) VALUES (?, ?, ?, '', ?, ?, NULL, 'A', '', NULL, '', ?)",
             nummer, f"Medewerker {nummer}", f"M{nummer}", nummer, f"m{nummer}@voorbeeld.invalid",
             f"token{nummer}")
        _sql(verbinding, "INSERT INTO contracturen (medewerker_id, jaar, uren) VALUES (?, 2026, 1500)",
             nummer)
    # Diensten: met code, met eigen tijden, met opmerking en met zelf ingevulde uren (0003)
    _sql(verbinding, "INSERT INTO dienst (datum, medewerker_id, dienstcode_id, dienstnaam_override, begin, "
         "eind, tijden_handmatig, uren_berekend, opmerking_tekst, opmerking_begin, opmerking_eind, "
         "google_event_id, versie, gewijzigd_op, uren_handmatig) VALUES ('2026-03-02', 1, 1, '', '07:00', "
         "'15:00', 0, 7.5, '', NULL, NULL, 'evt1', 3, '2026-03-01 10:00:00.000000', NULL)")
    _sql(verbinding, "INSERT INTO dienst (datum, medewerker_id, dienstcode_id, dienstnaam_override, begin, "
         "eind, tijden_handmatig, uren_berekend, opmerking_tekst, opmerking_begin, opmerking_eind, "
         "google_event_id, versie, gewijzigd_op, uren_handmatig) VALUES ('2026-03-07', 2, 1, '', '06:30', "
         "'15:00', 1, 12.0, 'Locatie A', '08:00', '09:00', '', 1, '2026-03-01 10:00:00.000000', NULL)")
    _sql(verbinding, "INSERT INTO dienst (datum, medewerker_id, dienstcode_id, dienstnaam_override, begin, "
         "eind, tijden_handmatig, uren_berekend, opmerking_tekst, opmerking_begin, opmerking_eind, "
         "google_event_id, versie, gewijzigd_op, uren_handmatig) VALUES ('2026-03-03', 3, 2, '', NULL, "
         "NULL, 0, 8.0, '', NULL, NULL, '', 1, '2026-03-01 10:00:00.000000', 8.0)")
    _sql(verbinding, "INSERT INTO dagopmerking (datum, tekst, handmatig) "
         "VALUES ('2026-03-02', 'Oefening', 1)")
    _sql(verbinding, "INSERT INTO vakantie (naam, datum_van, datum_tot) "
         "VALUES ('Voorjaarsvakantie', '2026-02-14', '2026-02-22')")
    # Gebruikers (zonder sessie_versie: die kolom komt pas in 0004)
    for gebruiker_id, naam, rol, medewerker in ((1, "planner", "beheerder", None),
                                                (2, "collega1", "gebruiker", 1)):
        _sql(verbinding, "INSERT INTO gebruiker (id, gebruikersnaam, weergavenaam, wachtwoord_hash, rol, "
             "medewerker_id, actief, moet_wachtwoord_wijzigen, aangemaakt_op, laatst_ingelogd) "
             "VALUES (?, ?, ?, ?, ?, ?, 1, 0, '2026-01-01 08:00:00.000000', NULL)",
             gebruiker_id, naam, naam.title(), hash_wachtwoord(WACHTWOORD), rol, medewerker)
    # Agenda-taken: één wachtend in de 'lokale tijd' van 1.1.2, één afgerond
    _sql(verbinding, "INSERT INTO sync_wachtrij (medewerker_id, datum, soort, niet_voor, pogingen, "
         "laatste_fout, status, aangemaakt_op, extra) VALUES (1, '2026-03-02', 'dag', "
         "'2099-01-01 00:00:00.000000', 2, 'tijdelijk', 'wacht', '2026-03-01 10:00:00.000000', '')")
    _sql(verbinding, "INSERT INTO sync_wachtrij (medewerker_id, datum, soort, niet_voor, pogingen, "
         "laatste_fout, status, aangemaakt_op, extra) VALUES (2, '2026-03-07', 'dag', "
         "'2026-03-01 10:00:00.000000', 0, '', 'klaar', '2026-03-01 10:00:00.000000', '')")
    # Loginpogingen (lokale tijd, vervallen bij de overgang naar UTC)
    for _ in range(4):
        _sql(verbinding, "INSERT INTO login_poging (gebruikersnaam, ip, tijdstip, gelukt) "
             "VALUES ('collega1', '127.0.0.1', '2099-01-01 00:00:00.000000', 0)")
    # Dubbele standaard feestdagen (konden in 1.1.2 ontstaan) en één eigen dag
    for _ in range(2):
        _sql(verbinding, "INSERT INTO feestdag (jaar, datum, naam, sleutel, actief) "
             "VALUES (2026, '2026-04-27', 'Koningsdag', 'koningsdag', 1)")
    _sql(verbinding, "INSERT INTO feestdag (jaar, datum, naam, sleutel, actief) "
         "VALUES (2026, '2026-03-02', 'Eigen dag', '', 1)")
    _sql(verbinding, "INSERT INTO logboek (tijdstempel, gebruiker, rol, actie, details, week, medewerker, "
         "dag, veld, oude_waarde, nieuwe_waarde) VALUES ('2026-03-01 10:00:00.000000', 'planner', "
         "'beheerder', 'Dienst gewijzigd', '', '2026-W10', 'Medewerker 1', 'ma', 'code', '', '4')")


@pytest.fixture
def app_112(tmp_path):
    """App met een database op revisie 0003 (versie 1.1.2), gevuld met fictieve data."""
    app = create_app(conftest.TestConfig(str(tmp_path)))
    with app.app_context():
        upgrade(directory=MIGRATIES, revision="0003")
        with db.engine.begin() as verbinding:
            _vul_versie_112(verbinding)
        yield app
        db.session.remove()


def _tel(tabel: str, waar: str = "1=1") -> int:
    with db.engine.connect() as verbinding:
        return verbinding.exec_driver_sql(f"SELECT count(*) FROM {tabel} WHERE {waar}").scalar()


def test_upgrade_van_112_houdt_alle_data_intact(app_112):
    from app.models import Dienst, Gebruiker, Medewerker, SyncTaak

    upgrade(directory=MIGRATIES)
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    with db.engine.connect() as verbinding:
        revisie = verbinding.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()

    config = Config()
    config.set_main_option("script_location", MIGRATIES)
    assert revisie == ScriptDirectory.from_config(config).get_current_head()

    # Medewerkers, contracturen, dienstcodes, diensten, opmerkingen, vakanties, logboek
    assert [m.naam for m in Medewerker.query.order_by(Medewerker.volgorde)] == \
        ["Medewerker 1", "Medewerker 2", "Medewerker 3"]
    assert _tel("contracturen") == 3 and _tel("dienstcode") == 2
    assert _tel("dagopmerking") == 1 and _tel("vakantie") == 1 and _tel("logboek") >= 1
    diensten = {d.datum: d for d in Dienst.query.all()}
    assert len(diensten) == 3
    eigen = diensten[date(2026, 3, 7)]
    assert (eigen.begin, eigen.eind, eigen.tijden_handmatig) == ("06:30", "15:00", True)
    assert eigen.uren_berekend == 12.0
    assert (eigen.opmerking_tekst, eigen.opmerking_begin, eigen.opmerking_eind) == \
        ("Locatie A", "08:00", "09:00")
    assert diensten[date(2026, 3, 2)].versie == 3 and diensten[date(2026, 3, 2)].google_event_id == "evt1"
    assert diensten[date(2026, 3, 3)].uren_handmatig == 8.0

    # Gebruikers: alles behouden, sessieversie begint op 0
    gebruikers = {g.gebruikersnaam: g for g in Gebruiker.query.all()}
    assert set(gebruikers) == {"planner", "collega1"}
    assert gebruikers["collega1"].medewerker_id == 1 and gebruikers["planner"].rol == "beheerder"
    assert all(g.sessie_versie == 0 for g in gebruikers.values())

    # Agenda-taken: wachtende taak direct aan de beurt (UTC), afgeronde blijft afgerond
    taken = {t.status: t for t in SyncTaak.query.all()}
    assert set(taken) == {"wacht", "klaar"}
    assert taken["wacht"].niet_voor.year == 2000 and taken["wacht"].pogingen == 2

    # Loginpogingen vervallen; dubbele feestdag opgeruimd, eigen dag blijft
    assert _tel("login_poging") == 0
    assert _tel("feestdag", "sleutel = 'koningsdag'") == 1 and _tel("feestdag", "sleutel = ''") == 1


def test_upgrade_van_112_iedereen_moet_opnieuw_inloggen(app_112):
    client = app_112.test_client()
    # Een sessie zoals 1.1.2 hem maakte (Flask-Login: alleen het gebruikers-ID)
    with client.session_transaction() as sessie:
        sessie["_user_id"] = "2"
        sessie["_fresh"] = True
    upgrade(directory=MIGRATIES)
    db.session.remove()

    antwoord = client.get("/mijn")
    assert antwoord.status_code == 302 and "/login" in antwoord.headers["Location"]
    # Met het bestaande wachtwoord gaat inloggen gewoon; de oude blokkade telt niet mee
    assert login(client, "collega1").status_code == 302
    assert client.get("/mijn").status_code == 200
    assert login(app_112.test_client(), "planner").status_code == 302


def test_upgrade_daarna_db_check_schoon(app_112):
    """Na de upgrade klopt het schema precies met de modellen (zoals 'flask db check')."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    upgrade(directory=MIGRATIES)
    with db.engine.connect() as verbinding:
        verschillen = compare_metadata(MigrationContext.configure(verbinding), db.metadata)
    assert verschillen == []
