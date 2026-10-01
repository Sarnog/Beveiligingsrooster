"""Persoonlijke API-tokens: aanmaken, controleren en intrekken.

Een token ziet eruit als 'br_<43 tekens>'. Alleen de SHA-256-hash wordt bewaard
(het token is lang en willekeurig, dus een trage hash zoals argon2 is niet nodig).
Een token is geldig zolang:
  - het niet verlopen of ingetrokken is;
  - de gebruiker actief is;
  - de sessiesleutel van de gebruiker niet veranderd is (wachtwoord gewijzigd of
    gereset, rol gewijzigd, gedeactiveerd, back-up teruggezet).
Te veel foute tokens vanaf één IP-adres: 15 minuten geblokkeerd (zoals bij inloggen).
"""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from ..extensions import db
from ..models import ApiToken, Gebruiker, LoginPoging
from . import klok, logboek

log = logging.getLogger(__name__)

VOORVOEGSEL = "br_"
GELDIGHEID_DAGEN = (30, 90, 180, 365)  # keuzes op de accountpagina
MAX_FOUTEN = 20  # foute tokens per IP ...
BLOKKADE_MINUTEN = 15  # ... binnen zoveel minuten
POGING_NAAM = "(api-token)"  # zo staan foute tokens in de tabel met loginpogingen


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def maak(gebruiker: Gebruiker, naam: str, dagen: int) -> tuple[str, ApiToken]:
    """Nieuw token. Geeft (token, record); het token zelf wordt nergens bewaard."""
    token = VOORVOEGSEL + secrets.token_urlsafe(32)
    record = ApiToken(gebruiker_id=gebruiker.id, naam=naam[:60], token_hash=hash_token(token),
                      prefix=token[:10], sessie_sleutel=gebruiker.get_id(),
                      aangemaakt_op=klok.utc_nu(), verloopt_op=klok.utc_nu() + timedelta(days=dagen))
    db.session.add(record)
    logboek.log("API-token aangemaakt", f"{record.naam} ({record.prefix}…), geldig tot "
                f"{record.verloopt_op:%d-%m-%Y}")
    return token, record


def trek_in(record: ApiToken) -> None:
    logboek.log("API-token ingetrokken", f"{record.naam} ({record.prefix}…)")
    db.session.delete(record)


def is_geldig(record: ApiToken) -> bool:
    gebruiker = record.gebruiker
    return (gebruiker is not None and gebruiker.actief and record.verloopt_op > klok.utc_nu()
            and hmac.compare_digest(record.sessie_sleutel, gebruiker.get_id()))


def ip_geblokkeerd(ip: str) -> bool:
    grens = klok.utc_nu() - timedelta(minutes=BLOKKADE_MINUTEN)
    return LoginPoging.query.filter(
        LoginPoging.gebruikersnaam == POGING_NAAM, LoginPoging.ip == ip,
        LoginPoging.gelukt.is_(False), LoginPoging.tijdstip >= grens,
    ).count() >= MAX_FOUTEN


def gebruiker_bij_token(token: str, ip: str) -> Gebruiker | None:
    """De gebruiker bij een geldig token, of None (fout token wordt geteld)."""
    record = None
    if token.startswith(VOORVOEGSEL) and len(token) <= 100:
        record = ApiToken.query.filter_by(token_hash=hash_token(token)).first()
    if record is None or not is_geldig(record):
        log.debug("Ongeldig of verlopen API-token vanaf %s", ip)
        db.session.add(LoginPoging(gebruikersnaam=POGING_NAAM, ip=ip, gelukt=False))
        db.session.commit()
        return None
    # 'Laatst gebruikt' hooguit eens per 5 minuten bijwerken (minder schrijven)
    nu = klok.utc_nu()
    if record.laatst_gebruikt is None or nu - record.laatst_gebruikt > timedelta(minutes=5):
        record.laatst_gebruikt = nu
        db.session.commit()
    return record.gebruiker
