"""Datamodel (SQLAlchemy). Eén klasse per tabel.

Keuzes:
- Alle koppelingen lopen via ID's. Een naamwijziging werkt daardoor overal door.
- Tijden worden opgeslagen als tekst 'HH:MM' (eenvoudig te lezen in SQLite).
- Uren worden bij opslaan berekend en bewaard (snelle overzichten).
"""

from datetime import date, datetime

from flask_login import UserMixin

from .extensions import db
from .services import klok

ROL_BEHEERDER = "beheerder"
ROL_GEBRUIKER = "gebruiker"


def nu() -> datetime:
    """Huidig tijdstip (lokale tijd van de server, zonder tijdzone-info)."""
    return klok.nu()


class Gebruiker(UserMixin, db.Model):
    """Een inlogaccount (beheerder of gebruiker)."""

    __tablename__ = "gebruiker"

    id = db.Column(db.Integer, primary_key=True)
    gebruikersnaam = db.Column(db.String(64), unique=True, nullable=False)
    weergavenaam = db.Column(db.String(120), nullable=False)
    wachtwoord_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default=ROL_GEBRUIKER)
    medewerker_id = db.Column(
        db.Integer, db.ForeignKey("medewerker.id", ondelete="SET NULL"), nullable=True
    )
    actief = db.Column(db.Boolean, nullable=False, default=True)
    moet_wachtwoord_wijzigen = db.Column(db.Boolean, nullable=False, default=False)
    aangemaakt_op = db.Column(db.DateTime, nullable=False, default=nu)
    laatst_ingelogd = db.Column(db.DateTime, nullable=True)

    medewerker = db.relationship("Medewerker")

    @property
    def is_beheerder(self) -> bool:
        return self.rol == ROL_BEHEERDER

    @property
    def is_active(self) -> bool:  # gebruikt door Flask-Login
        return bool(self.actief)


class Medewerker(db.Model):
    """Een collega in het rooster."""

    __tablename__ = "medewerker"

    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(120), nullable=False)
    initialen = db.Column(db.String(10), unique=True, nullable=False)
    functie_opmerking = db.Column(db.String(120), nullable=False, default="")
    volgorde = db.Column(db.Integer, nullable=False, default=0)
    email = db.Column(db.String(255), nullable=False, default="")
    # Gearchiveerd vanaf deze datum: niet meer zichtbaar in weken die daarna beginnen
    gearchiveerd_vanaf = db.Column(db.Date, nullable=True)
    # Google Agenda: '' = niet gekoppeld, 'A' = eigen agenda via app, 'B' = gedeelde agenda
    agenda_modus = db.Column(db.String(1), nullable=False, default="")
    agenda_id = db.Column(db.String(255), nullable=False, default="")
    agenda_laatst_gesync = db.Column(db.DateTime, nullable=True)
    agenda_laatste_fout = db.Column(db.Text, nullable=False, default="")
    # Geheim token voor de ICS-feed ('' = geen feed)
    ics_token = db.Column(db.String(64), nullable=False, default="", index=True)

    contracturen = db.relationship(
        "Contracturen", back_populates="medewerker", cascade="all, delete-orphan"
    )

    def is_zichtbaar_op(self, datum: date) -> bool:
        """True als de medewerker op/na deze datum nog in het rooster hoort."""
        return self.gearchiveerd_vanaf is None or datum < self.gearchiveerd_vanaf

    def contracturen_voor(self, jaar: int) -> float | None:
        """Contracturen voor een jaar. Zonder eigen waarde: het laatste eerdere jaar."""
        kandidaten = [c for c in self.contracturen if c.jaar <= jaar]
        if not kandidaten:
            return None
        return max(kandidaten, key=lambda c: c.jaar).uren


class Contracturen(db.Model):
    """Contracturen per medewerker per jaar."""

    __tablename__ = "contracturen"

    id = db.Column(db.Integer, primary_key=True)
    medewerker_id = db.Column(
        db.Integer, db.ForeignKey("medewerker.id", ondelete="CASCADE"), nullable=False
    )
    jaar = db.Column(db.Integer, nullable=False)
    uren = db.Column(db.Float, nullable=False)

    medewerker = db.relationship("Medewerker", back_populates="contracturen")

    __table_args__ = (db.UniqueConstraint("medewerker_id", "jaar"),)


class Dienstcode(db.Model):
    """Een dienstcode (het nummer dat de planner in het code-raster typt)."""

    __tablename__ = "dienstcode"

    id = db.Column(db.Integer, primary_key=True)
    nummer = db.Column(db.Integer, unique=True, nullable=False)
    omschrijving = db.Column(db.String(60), nullable=False)
    std_begin = db.Column(db.String(5), nullable=True)  # 'HH:MM' of leeg
    std_eind = db.Column(db.String(5), nullable=True)
    std_uren = db.Column(db.Float, nullable=True)  # alleen informatief
    kleur_achtergrond = db.Column(db.String(7), nullable=False, default="#FFFFFF")
    kleur_tekst = db.Column(db.String(7), nullable=False, default="#000000")
    vet = db.Column(db.Boolean, nullable=False, default=True)
    cursief = db.Column(db.Boolean, nullable=False, default=False)
    in_agenda = db.Column(db.Boolean, nullable=False, default=True)
    hele_dag_zonder_tijden = db.Column(db.Boolean, nullable=False, default=False)
    actief = db.Column(db.Boolean, nullable=False, default=True)


class OpmerkingKleurregel(db.Model):
    """Kleur voor een opmerkingstekst, bijvoorbeeld een locatie ('Locatie X')."""

    __tablename__ = "opmerking_kleurregel"

    id = db.Column(db.Integer, primary_key=True)
    tekst = db.Column(db.String(60), unique=True, nullable=False)
    kleur_achtergrond = db.Column(db.String(7), nullable=False, default="#FFFFFF")
    # Optionele tweede kleur: dan wordt het een verloop (zoals in Excel)
    kleur_achtergrond2 = db.Column(db.String(7), nullable=True)
    kleur_tekst = db.Column(db.String(7), nullable=False, default="#000000")


class Dienst(db.Model):
    """Eén roosterregel: één medewerker op één datum."""

    __tablename__ = "dienst"

    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, nullable=False, index=True)
    medewerker_id = db.Column(
        db.Integer, db.ForeignKey("medewerker.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    dienstcode_id = db.Column(
        db.Integer, db.ForeignKey("dienstcode.id", ondelete="RESTRICT"), nullable=True,
        index=True,
    )
    # Vrije dienstnaam, bijvoorbeeld bij een import zonder code
    dienstnaam_override = db.Column(db.String(60), nullable=False, default="")
    begin = db.Column(db.String(5), nullable=True)
    eind = db.Column(db.String(5), nullable=True)
    tijden_handmatig = db.Column(db.Boolean, nullable=False, default=False)
    uren_berekend = db.Column(db.Float, nullable=True)
    opmerking_tekst = db.Column(db.String(120), nullable=False, default="")
    opmerking_begin = db.Column(db.String(5), nullable=True)
    opmerking_eind = db.Column(db.String(5), nullable=True)
    google_event_id = db.Column(db.String(255), nullable=False, default="")
    # Optimistic locking: elke wijziging verhoogt het versienummer
    versie = db.Column(db.Integer, nullable=False, default=1)
    gewijzigd_op = db.Column(db.DateTime, nullable=False, default=nu, onupdate=nu)

    medewerker = db.relationship("Medewerker")
    dienstcode = db.relationship("Dienstcode")

    __table_args__ = (db.UniqueConstraint("medewerker_id", "datum"),)

    @property
    def dienstnaam(self) -> str:
        """De naam die in regel c van het rooster staat."""
        if self.dienstcode is not None:
            return self.dienstcode.omschrijving
        return self.dienstnaam_override or ""

    @property
    def is_leeg(self) -> bool:
        """True als er niets in deze regel staat (mag dan weg uit de database)."""
        return (
            self.dienstcode_id is None
            and not self.dienstnaam_override
            and not self.begin
            and not self.eind
            and not self.opmerking_tekst
            and not self.opmerking_begin
            and not self.opmerking_eind
        )


class Dagopmerking(db.Model):
    """Handmatige dagopmerking (rij 3). Automatische tekst wordt niet opgeslagen."""

    __tablename__ = "dagopmerking"

    id = db.Column(db.Integer, primary_key=True)
    datum = db.Column(db.Date, unique=True, nullable=False)
    # Lege tekst betekent: de automatische tekst bewust weggehaald
    tekst = db.Column(db.String(120), nullable=False, default="")
    handmatig = db.Column(db.Boolean, nullable=False, default=True)


class Vakantie(db.Model):
    """Een schoolvakantie of andere vakantieperiode."""

    __tablename__ = "vakantie"

    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(80), nullable=False)
    datum_van = db.Column(db.Date, nullable=False)
    datum_tot = db.Column(db.Date, nullable=False)


class Feestdag(db.Model):
    """Feestdag of eigen roostervrije dag, per jaar."""

    __tablename__ = "feestdag"

    id = db.Column(db.Integer, primary_key=True)
    jaar = db.Column(db.Integer, nullable=False, index=True)
    datum = db.Column(db.Date, nullable=False)
    naam = db.Column(db.String(80), nullable=False)
    # Sleutel van een automatische feestdag (bijv. 'koningsdag'); leeg bij eigen dag
    sleutel = db.Column(db.String(40), nullable=False, default="")
    actief = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def is_eigen(self) -> bool:
        return not self.sleutel


class Instelling(db.Model):
    """Eenvoudige sleutel/waarde-opslag voor instellingen."""

    __tablename__ = "instelling"

    sleutel = db.Column(db.String(64), primary_key=True)
    waarde = db.Column(db.Text, nullable=False, default="")


class Logboek(db.Model):
    """Eén regel in het logboek (wie deed wat, wanneer)."""

    __tablename__ = "logboek"

    id = db.Column(db.Integer, primary_key=True)
    tijdstempel = db.Column(db.DateTime, nullable=False, default=nu, index=True)
    gebruiker = db.Column(db.String(64), nullable=False, default="")
    rol = db.Column(db.String(20), nullable=False, default="")
    actie = db.Column(db.String(60), nullable=False, index=True)
    details = db.Column(db.Text, nullable=False, default="")
    week = db.Column(db.String(12), nullable=False, default="")  # bijv. '2026-W14'
    medewerker = db.Column(db.String(120), nullable=False, default="")
    dag = db.Column(db.String(10), nullable=False, default="")  # 'dd-mm-jjjj'
    veld = db.Column(db.String(40), nullable=False, default="")
    oude_waarde = db.Column(db.Text, nullable=False, default="")
    nieuwe_waarde = db.Column(db.Text, nullable=False, default="")


class LoginPoging(db.Model):
    """Inlogpogingen, voor de beperking van 5 pogingen per 15 minuten."""

    __tablename__ = "login_poging"

    id = db.Column(db.Integer, primary_key=True)
    gebruikersnaam = db.Column(db.String(64), nullable=False, index=True)
    ip = db.Column(db.String(64), nullable=False, index=True)
    tijdstip = db.Column(db.DateTime, nullable=False, default=nu, index=True)
    gelukt = db.Column(db.Boolean, nullable=False, default=False)


class SyncTaak(db.Model):
    """Wachtrij voor Google Agenda-synchronisatie (verwerkt door de worker)."""

    __tablename__ = "sync_wachtrij"

    id = db.Column(db.Integer, primary_key=True)
    medewerker_id = db.Column(
        db.Integer, db.ForeignKey("medewerker.id", ondelete="CASCADE"), nullable=False
    )
    datum = db.Column(db.Date, nullable=True)  # leeg = volledige synchronisatie
    soort = db.Column(db.String(20), nullable=False, default="dag")  # dag/volledig/ontkoppel
    # Niet eerder uitvoeren dan dit tijdstip (debounce en backoff)
    niet_voor = db.Column(db.DateTime, nullable=False, default=nu, index=True)
    pogingen = db.Column(db.Integer, nullable=False, default=0)
    laatste_fout = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(12), nullable=False, default="wacht", index=True)
    aangemaakt_op = db.Column(db.DateTime, nullable=False, default=nu)
    # Extra gegevens, bijvoorbeeld een event-id dat verwijderd moet worden
    extra = db.Column(db.Text, nullable=False, default="")
