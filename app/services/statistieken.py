"""Beheer → Statistieken: een alleen-lezen overzicht voor de planner (sinds 1.6.0).

Vier blokken: Google Agenda (mislukte synchronisatie, wachtrij), back-ups (laatste geslaagde,
aantal, te oud), rooster (diensten, uren tegenover contracturen, zelf ingevulde uren en
afwijkende tijden) en beveiliging (mislukte inlogpogingen, blokkades, actieve API-tokens).
Alles met een vast aantal query's, ongeacht het aantal medewerkers (geen N+1).
meldingen() is de korte versie voor de Beheer-startpagina.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import aliased, joinedload

from ..extensions import db
from ..models import ApiToken, Dienst, Gebruiker, Logboek, LoginPoging, Medewerker, SyncTaak
from . import backup, instellingen, klok
from .kalender import aantal_weken, eerste_en_laatste_dag_isojaar
from .overzichten import uren_overzicht

BACKUP_MAX_DAGEN = 2  # ouder dan dit: waarschuwing
MAX_REGELS = 100  # lijsten met diensten: hooguit zoveel regels (het aantal staat erbij)
STEMPEL = re.compile(r"^rooster-(\d{8}-\d{6})")


@dataclass
class AgendaStatistiek:
    fouten: list[Medewerker]
    wachtrij: dict[str, int]
    oudste_wachtend: SyncTaak | None


@dataclass
class BackupStatistiek:
    laatste_automatisch: dict | None  # {'naam', 'grootte', 'tijd'} (zie backup.lijst_backups)
    laatste_label: dict | None
    aantal: int
    totale_grootte: int
    te_oud: bool
    laatste_mislukt: Logboek | None

    @property
    def tijdstip_automatisch(self) -> datetime | None:
        return _tijdstip(self.laatste_automatisch)

    @property
    def tijdstip_label(self) -> datetime | None:
        return _tijdstip(self.laatste_label)


@dataclass
class UrenRij:
    medewerker: Medewerker
    contracturen: float | None
    gewerkt: float  # t/m de huidige week
    gepland: float  # het hele jaar
    contract_tot_nu: float | None  # contracturen naar rato van de weken t/m nu

    @property
    def verschil(self) -> float | None:
        return None if self.contract_tot_nu is None else self.gewerkt - self.contract_tot_nu


@dataclass
class RoosterStatistiek:
    jaar: int
    week: int
    aantal_diensten: int
    uren: list[UrenRij]
    handmatige_uren: list[Dienst]
    aantal_handmatig: int
    afwijkende_tijden: list[Dienst]
    aantal_afwijkend: int
    mogelijk_dubbel: list[Dienst]  # dienst 1 met zelf ingevulde uren naast een dienst 2


@dataclass
class BeveiligingStatistiek:
    mislukte_pogingen: int
    per_bron: list[tuple[str, str, int]]  # (gebruikersnaam, ip, aantal), meeste eerst
    blokkades: list[Logboek]
    actieve_tokens: list[ApiToken]


@dataclass
class Statistieken:
    agenda: AgendaStatistiek
    backups: BackupStatistiek
    rooster: RoosterStatistiek
    beveiliging: BeveiligingStatistiek
    meldingen: list[str] = field(default_factory=list)


def _tijdstip(back_up: dict | None) -> datetime | None:
    """Tijdstip uit de naam (rooster-JJJJMMDD-UUMMSS...), zoals de app hem maakte."""
    if back_up is None:
        return None
    gevonden = STEMPEL.match(back_up["naam"])
    return datetime.strptime(gevonden.group(1), "%Y%m%d-%H%M%S") if gevonden else None


def agenda() -> AgendaStatistiek:
    fouten = (Medewerker.query.filter(Medewerker.agenda_laatste_fout != "")
              .order_by(Medewerker.volgorde, Medewerker.naam).all())
    wachtrij = {"wacht": 0, "bezig": 0, "fout": 0}
    wachtrij.update(dict(db.session.query(SyncTaak.status, db.func.count(SyncTaak.id))
                         .group_by(SyncTaak.status).all()))
    oudste = (SyncTaak.query.filter_by(status="wacht").order_by(SyncTaak.aangemaakt_op, SyncTaak.id)
              .first())
    return AgendaStatistiek(fouten, wachtrij, oudste)


def backups() -> BackupStatistiek:
    geldig = [b for b in backup.lijst_backups() if b["grootte"] > 0]  # nieuwste eerst
    automatisch = next((b for b in geldig if backup.AUTOMATISCH.match(b["naam"])), None)
    gelabeld = next((b for b in geldig if not backup.AUTOMATISCH.match(b["naam"])), None)
    tijdstip = _tijdstip(automatisch)
    te_oud = tijdstip is None or klok.nu() - tijdstip > timedelta(days=BACKUP_MAX_DAGEN)
    mislukt = Logboek.query.filter_by(actie="Back-up mislukt").order_by(Logboek.id.desc()).first()
    return BackupStatistiek(automatisch, gelabeld, len(geldig), sum(b["grootte"] for b in geldig),
                            te_oud, mislukt)


def _niet_leeg(model=Dienst):
    """SQL-voorwaarde: er staat iets in de dienst (zie Dienst.is_leeg)."""
    return or_(model.dienstcode_id.isnot(None), model.dienstnaam_override != "", model.begin.isnot(None),
               model.eind.isnot(None), model.opmerking_tekst != "", model.opmerking_begin.isnot(None),
               model.opmerking_eind.isnot(None), model.uren_handmatig.isnot(None))


def rooster() -> RoosterStatistiek:
    jaar, week, _ = klok.vandaag().isocalendar()
    eerste, laatste = eerste_en_laatste_dag_isojaar(jaar)
    in_jaar = (Dienst.datum >= eerste, Dienst.datum <= laatste)
    aantal = db.session.query(db.func.count(Dienst.id)).filter(*in_jaar, _niet_leeg()).scalar()
    weken = aantal_weken(jaar)
    uren = [UrenRij(r.medewerker, r.contracturen,
                    gewerkt=sum(u for w, u in r.per_week.items() if w <= week), gepland=r.gewerkt,
                    contract_tot_nu=None if r.contracturen is None else r.contracturen * week / weken)
            for r in uren_overzicht(jaar)]

    def lijst(*voorwaarden) -> tuple[list[Dienst], int]:
        query = Dienst.query.filter(*in_jaar, *voorwaarden)
        totaal = query.count()
        regels = (query.options(joinedload(Dienst.medewerker), joinedload(Dienst.dienstcode))
                  .order_by(Dienst.datum, Dienst.medewerker_id, Dienst.volgnummer).limit(MAX_REGELS).all())
        return regels, totaal

    handmatig, aantal_handmatig = lijst(Dienst.uren_handmatig.isnot(None))
    afwijkend, aantal_afwijkend = lijst(Dienst.tijden_handmatig.is_(True), Dienst.dienstcode_id.isnot(None))
    tweede = aliased(Dienst)
    dubbel = (Dienst.query.options(joinedload(Dienst.medewerker))
              .join(tweede, (tweede.medewerker_id == Dienst.medewerker_id) & (tweede.datum == Dienst.datum)
                    & (tweede.volgnummer == 2))
              .filter(*in_jaar, Dienst.volgnummer == 1, Dienst.uren_handmatig.isnot(None), _niet_leeg(tweede))
              .order_by(Dienst.datum, Dienst.medewerker_id).limit(MAX_REGELS).all())
    return RoosterStatistiek(jaar, week, aantal, uren, handmatig, aantal_handmatig, afwijkend,
                             aantal_afwijkend, dubbel)


def beveiliging() -> BeveiligingStatistiek:
    grens = klok.utc_nu() - timedelta(hours=24)
    mislukt = LoginPoging.query.filter(LoginPoging.gelukt.is_(False), LoginPoging.tijdstip >= grens)
    per_bron = (db.session.query(LoginPoging.gebruikersnaam, LoginPoging.ip, db.func.count(LoginPoging.id))
                .filter(LoginPoging.gelukt.is_(False), LoginPoging.tijdstip >= grens)
                .group_by(LoginPoging.gebruikersnaam, LoginPoging.ip)
                .order_by(db.func.count(LoginPoging.id).desc(), LoginPoging.gebruikersnaam).limit(20).all())
    blokkades = (Logboek.query.filter(Logboek.actie == "Login geblokkeerd",
                                      Logboek.tijdstempel >= klok.nu() - timedelta(hours=24))
                 .order_by(Logboek.id.desc()).limit(MAX_REGELS).all())
    # Geldig zoals api_tokens.is_geldig, maar met één keer de sessie-generatie (geen query per token)
    generatie = instellingen.lees("sessie_generatie")
    tokens = [t for t in ApiToken.query.options(joinedload(ApiToken.gebruiker))
              .filter(ApiToken.verloopt_op > klok.utc_nu()).order_by(ApiToken.aangemaakt_op).all()
              if t.gebruiker is not None and t.gebruiker.actief
              and t.sessie_sleutel == _sessiesleutel(t.gebruiker, generatie)]
    return BeveiligingStatistiek(mislukt.count(), [tuple(r) for r in per_bron], blokkades, tokens)


def _sessiesleutel(gebruiker: Gebruiker, generatie: str) -> str:
    return f"{gebruiker.id}:{gebruiker.sessie_versie or 0}:{generatie}"


def meldingen(agenda_stat: AgendaStatistiek | None = None, backup_stat: BackupStatistiek | None = None,
              aantal_dubbel: int | None = None) -> list[str]:
    """Korte meldingen voor de Beheer-startpagina ([] = alles in orde)."""
    agenda_stat = agenda_stat or agenda()
    backup_stat = backup_stat or backups()
    resultaat = []
    if agenda_stat.fouten or agenda_stat.wachtrij.get("fout"):
        resultaat.append(f"Google Agenda: {len(agenda_stat.fouten)} medewerker(s) met een mislukte "
                         f"synchronisatie, {agenda_stat.wachtrij.get('fout', 0)} mislukte taken.")
    if backup_stat.te_oud:
        tijdstip = backup_stat.tijdstip_automatisch
        resultaat.append("Back-up: er is nog geen automatische back-up." if tijdstip is None else
                         f"Back-up: de laatste automatische back-up is van {tijdstip:%d-%m-%Y %H:%M} "
                         f"(ouder dan {BACKUP_MAX_DAGEN} dagen). Draait de worker?")
    if aantal_dubbel is None:
        aantal_dubbel = _aantal_dubbel()
    if aantal_dubbel:
        resultaat.append(f"Rooster: {aantal_dubbel} dag(en) met een tweede dienst én zelf ingevulde uren "
                         "bij dienst 1 (mogelijk dubbel geteld).")
    return resultaat


def _aantal_dubbel() -> int:
    tweede = aliased(Dienst)
    return (db.session.query(db.func.count(Dienst.id))
            .join(tweede, (tweede.medewerker_id == Dienst.medewerker_id) & (tweede.datum == Dienst.datum)
                  & (tweede.volgnummer == 2))
            .filter(Dienst.volgnummer == 1, Dienst.uren_handmatig.isnot(None), _niet_leeg(tweede)).scalar())


def verzamel() -> Statistieken:
    resultaat = Statistieken(agenda(), backups(), rooster(), beveiliging())
    resultaat.meldingen = meldingen(resultaat.agenda, resultaat.backups)
    return resultaat


def grootte_tekst(aantal_bytes: int) -> str:
    """1536 -> '1,5 kB'."""
    for eenheid, deler in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("kB", 1024)):
        if aantal_bytes >= deler:
            return f"{aantal_bytes / deler:.1f} {eenheid}".replace(".", ",")
    return f"{aantal_bytes} B"
