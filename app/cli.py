"""Commando's voor de command line (noodgevallen en onderhoud).

Aanroepen in Docker, vanuit de map met docker-compose.yml. Gebruik altijd
'-u rooster', anders worden nieuwe bestanden in ./data van root:
    docker compose exec -u rooster web flask reset-wachtwoord <gebruiker>
    docker compose exec -u rooster web flask maak-beheerder
    docker compose exec -u rooster web flask setup-code
    docker compose exec -u rooster web flask backup
    docker compose exec -u rooster web flask terugzetten <naam-van-de-back-up>
    docker compose exec -u rooster web flask herbereken-uren
"""

import getpass
import re
import secrets

import click
from flask import Flask

from .extensions import db
from .models import ROL_BEHEERDER, Gebruiker
from .services import instellingen, logboek, setup_code
from .services.wachtwoorden import hash_wachtwoord, wachtwoord_fout


def _vraag_wachtwoord() -> str:
    """Vraag een nieuw wachtwoord (twee keer), of maak er een als er geen terminal is."""
    try:
        wachtwoord = getpass.getpass("Nieuw wachtwoord (minimaal 10 tekens): ")
        herhaling = getpass.getpass("Nog een keer: ")
    except (EOFError, OSError):
        wachtwoord = herhaling = ""
    if not wachtwoord:
        wachtwoord = secrets.token_urlsafe(9)
        click.echo(f"Tijdelijk wachtwoord: {wachtwoord}")
        return wachtwoord
    if fout := wachtwoord_fout(wachtwoord, herhaling):
        raise click.ClickException(fout)
    return wachtwoord


def registreer_commando_s(app: Flask) -> None:
    @app.cli.command("reset-wachtwoord")
    @click.argument("gebruikersnaam")
    def reset_wachtwoord(gebruikersnaam: str):
        """Zet een nieuw wachtwoord voor een gebruiker en activeer het account."""
        gebruiker = Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam.lower()).first()
        if gebruiker is None:
            raise click.ClickException(f"Gebruiker '{gebruikersnaam}' bestaat niet.")
        wachtwoord = _vraag_wachtwoord()
        gebruiker.wachtwoord_hash = hash_wachtwoord(wachtwoord)
        gebruiker.actief = True
        gebruiker.moet_wachtwoord_wijzigen = True
        gebruiker.maak_sessies_ongeldig()
        logboek.log("Wachtwoord gereset", "Via command line", gebruiker="cli",
                    nieuw=gebruiker.gebruikersnaam)
        db.session.commit()
        click.echo(f"Wachtwoord van '{gebruiker.gebruikersnaam}' is gereset. "
                   "Bij de volgende login moet een nieuw wachtwoord gekozen worden.")

    @app.cli.command("maak-beheerder")
    @click.option("--gebruikersnaam", prompt="Gebruikersnaam")
    @click.option("--weergavenaam", prompt="Weergavenaam")
    def maak_beheerder(gebruikersnaam: str, weergavenaam: str):
        """Maak een (extra) beheerder aan, of maak een bestaande gebruiker beheerder."""
        gebruikersnaam = gebruikersnaam.strip().lower()
        gebruiker = Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).first()
        wachtwoord = _vraag_wachtwoord()
        if gebruiker is None:
            gebruiker = Gebruiker(gebruikersnaam=gebruikersnaam, weergavenaam=weergavenaam,
                                  wachtwoord_hash="")
            db.session.add(gebruiker)
        gebruiker.rol = ROL_BEHEERDER
        gebruiker.actief = True
        gebruiker.maak_sessies_ongeldig()
        gebruiker.wachtwoord_hash = hash_wachtwoord(wachtwoord)
        gebruiker.moet_wachtwoord_wijzigen = False
        logboek.log("Beheerder aangemaakt", "Via command line", gebruiker="cli",
                    nieuw=gebruikersnaam)
        db.session.commit()
        click.echo(f"'{gebruikersnaam}' is nu beheerder.")

    @app.cli.command("setup-code")
    def toon_setup_code():
        """Toon de setup-code (alleen zolang de setup niet is afgerond)."""
        if instellingen.setup_voltooid():
            click.echo("De setup is al afgerond; er is geen setup-code meer nodig.")
            return
        click.echo(f"Setup-code: {setup_code.haal_of_maak_code()}")

    @app.cli.command("herbereken-uren")
    @click.confirmation_option(prompt="Dit wijzigt ook historische totalen. Doorgaan?")
    def herbereken_uren():
        """Alle uren opnieuw berekenen (na wijziging van toeslagfactoren)."""
        from .services.rooster import herbereken_alle

        gewijzigd = herbereken_alle()
        logboek.log("Uren herberekend", f"Via command line: {gewijzigd} gewijzigd", gebruiker="cli")
        db.session.commit()
        click.echo(f"Klaar: {gewijzigd} diensten gewijzigd.")

    @app.cli.command("backup")
    @click.option("--label", default="", help="Bijvoorbeeld 'voor-update'")
    def backup_maken(label: str):
        """Maak nu een back-up van de database (in <datamap>/backups)."""
        from .services import backup

        if label and not re.fullmatch(r"[a-z0-9-]{1,40}", label):
            raise click.ClickException("Het label mag alleen kleine letters, cijfers en '-' bevatten "
                                       "(bijv. 'voor-update').")
        click.echo(f"Back-up gemaakt: {backup.maak_backup(label)}")

    @app.cli.command("terugzetten")
    @click.argument("naam")
    @click.confirmation_option(prompt="De huidige stand wordt vervangen door deze back-up. Doorgaan?")
    def terugzetten(naam: str):
        """Zet een back-up uit <datamap>/backups terug (noodgeval, als de website niet werkt).

        Maakt eerst zelf een veiligheidsback-up; daarna moet iedereen opnieuw inloggen.
        """
        from .services import backup

        pad = backup.pad_van(naam)
        if pad is None:
            raise click.ClickException(f"Onbekende back-up '{naam}'. Kies een naam uit Beheer → Back-ups "
                                       "of uit de map backups.")
        try:
            veiligheid = backup.zet_terug(pad)
        except ValueError as fout:
            raise click.ClickException(str(fout)) from fout
        logboek.log("Back-up teruggezet", f"{naam} (via command line)", gebruiker="cli", oud=veiligheid)
        db.session.commit()
        click.echo(f"Back-up {naam} is teruggezet. De vorige stand is bewaard als {veiligheid}. "
                   "Iedereen moet opnieuw inloggen.")

    @app.cli.command("logboek-opschonen")
    def logboek_opschonen():
        """Verwijder logboekregels ouder dan de bewaartermijn."""
        click.echo(f"{logboek.opschonen()} regels verwijderd.")
