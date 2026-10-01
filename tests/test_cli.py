"""Command line-commando's (flask reset-wachtwoord, maak-beheerder, ...)."""

import getpass
import os

import pytest

from app.extensions import db
from app.models import Dienst, Gebruiker, Logboek, Medewerker
from app.services import backup, instellingen, setup_code
from app.services.wachtwoorden import controleer_wachtwoord

NIEUW = "nieuwwachtwoord1"


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


@pytest.fixture
def wachtwoord_invoer(monkeypatch):
    """Wat de beheerder bij de wachtwoordvraag typt (twee keer)."""
    antwoorden = []

    def invoer(antwoord: str, herhaling: str | None = None):
        antwoorden[:] = [antwoord, antwoord if herhaling is None else herhaling]
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": antwoorden.pop(0))

    return invoer


def test_reset_wachtwoord(runner, klaar, wachtwoord_invoer):
    wachtwoord_invoer(NIEUW)
    gebruiker = db.session.get(Gebruiker, klaar["gebruiker"].id)
    gebruiker.actief = False
    versie = gebruiker.sessie_versie
    db.session.commit()
    resultaat = runner.invoke(args=["reset-wachtwoord", "Collega"])
    assert resultaat.exit_code == 0 and "is gereset" in resultaat.output
    gebruiker = db.session.get(Gebruiker, gebruiker.id)
    assert controleer_wachtwoord(gebruiker.wachtwoord_hash, NIEUW)
    assert gebruiker.actief and gebruiker.moet_wachtwoord_wijzigen
    assert gebruiker.sessie_versie == versie + 1  # oude sessies ongeldig
    assert Logboek.query.filter_by(actie="Wachtwoord gereset", gebruiker="cli").count() == 1


def test_reset_wachtwoord_onbekende_gebruiker(runner, klaar):
    resultaat = runner.invoke(args=["reset-wachtwoord", "bestaat-niet"])
    assert resultaat.exit_code != 0 and "bestaat niet" in resultaat.output


def test_reset_wachtwoord_te_kort_en_ongelijk(runner, klaar, wachtwoord_invoer):
    wachtwoord_invoer("kort")
    assert "minimaal" in runner.invoke(args=["reset-wachtwoord", "collega"]).output
    wachtwoord_invoer(NIEUW, NIEUW + "x")
    assert "niet gelijk" in runner.invoke(args=["reset-wachtwoord", "collega"]).output


def test_reset_wachtwoord_zonder_terminal_geeft_tijdelijk_wachtwoord(runner, klaar, monkeypatch):
    def geen_terminal(prompt=""):
        raise EOFError

    monkeypatch.setattr(getpass, "getpass", geen_terminal)
    resultaat = runner.invoke(args=["reset-wachtwoord", "collega"])
    tijdelijk = resultaat.output.split("Tijdelijk wachtwoord: ")[1].split()[0]
    gebruiker = Gebruiker.query.filter_by(gebruikersnaam="collega").one()
    assert controleer_wachtwoord(gebruiker.wachtwoord_hash, tijdelijk)


def test_maak_beheerder_nieuw_en_bestaand(runner, klaar, wachtwoord_invoer):
    wachtwoord_invoer(NIEUW)
    resultaat = runner.invoke(args=["maak-beheerder", "--gebruikersnaam", " Noodbeheer ",
                                    "--weergavenaam", "Nood"])
    assert resultaat.exit_code == 0
    nieuw = Gebruiker.query.filter_by(gebruikersnaam="noodbeheer").one()
    assert nieuw.is_beheerder and not nieuw.moet_wachtwoord_wijzigen
    # Een bestaande gewone gebruiker beheerder maken
    wachtwoord_invoer(NIEUW)
    runner.invoke(args=["maak-beheerder", "--gebruikersnaam", "collega", "--weergavenaam", "C"])
    assert Gebruiker.query.filter_by(gebruikersnaam="collega").one().is_beheerder


def test_setup_code(runner, app):
    resultaat = runner.invoke(args=["setup-code"])
    assert setup_code.lees_code() in resultaat.output
    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    assert "al afgerond" in runner.invoke(args=["setup-code"]).output


def test_backup(runner, klaar):
    resultaat = runner.invoke(args=["backup", "--label", "voor-update"])
    assert resultaat.exit_code == 0
    namen = [b["naam"] for b in backup.lijst_backups()]
    assert len(namen) == 1 and namen[0].endswith("-voor-update.db")
    assert os.path.basename(resultaat.output.strip().split(": ")[1]) == namen[0]


def test_herbereken_uren(runner, klaar):
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.commit()
    from datetime import date

    db.session.add(Dienst(medewerker_id=medewerker.id, datum=date(2026, 3, 7), begin="07:15",
                          eind="15:45", uren_berekend=1.0, opmerking_tekst=""))
    db.session.commit()
    assert runner.invoke(args=["herbereken-uren"], input="n\n").exit_code != 0  # zonder bevestiging
    resultaat = runner.invoke(args=["herbereken-uren", "--yes"])
    assert "1 diensten gewijzigd" in resultaat.output
    assert Dienst.query.one().uren_berekend == 12.0  # zaterdag: 8 x 1,5


def test_logboek_opschonen(runner, klaar):
    from datetime import datetime

    db.session.add(Logboek(actie="Oud", tijdstempel=datetime(2000, 1, 1)))
    db.session.commit()
    assert "1 regels verwijderd" in runner.invoke(args=["logboek-opschonen"]).output


def test_terugzetten(runner, gemigreerd):
    resultaat = runner.invoke(args=["backup", "--label", "handmatig"])
    naam = os.path.basename(resultaat.output.strip().split(": ")[1])
    db.session.add(Medewerker(naam="Na de back-up", initialen="NB"))
    db.session.commit()
    assert runner.invoke(args=["terugzetten", naam], input="n\n").exit_code != 0  # zonder bevestiging
    assert Medewerker.query.filter_by(naam="Na de back-up").count() == 1
    resultaat = runner.invoke(args=["terugzetten", naam, "--yes"])
    assert resultaat.exit_code == 0 and "teruggezet" in resultaat.output
    db.session.remove()
    assert Medewerker.query.filter_by(naam="Na de back-up").count() == 0
    assert Logboek.query.filter_by(actie="Back-up teruggezet", gebruiker="cli").count() == 1
    assert any(b["naam"].endswith("-voor-terugzetten.db") for b in backup.lijst_backups())


def test_terugzetten_onbekend_of_kapot(runner, klaar):
    resultaat = runner.invoke(args=["terugzetten", "rooster-20000101-000000.db", "--yes"])
    assert resultaat.exit_code != 0 and "Onbekende back-up" in resultaat.output
    pad = os.path.join(backup.backup_map(), "rooster-20000101-000000.db")
    os.makedirs(backup.backup_map(), exist_ok=True)
    with open(pad, "wb") as bestand:
        bestand.write(b"geen database")
    resultaat = runner.invoke(args=["terugzetten", "rooster-20000101-000000.db", "--yes"])
    assert resultaat.exit_code != 0 and "geen geldige" in resultaat.output
