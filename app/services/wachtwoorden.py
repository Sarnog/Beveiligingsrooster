"""Wachtwoorden hashen en controleren met argon2 (via argon2-cffi)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MINIMALE_LENGTE = 10

_hasher = PasswordHasher()


def hash_wachtwoord(wachtwoord: str) -> str:
    return _hasher.hash(wachtwoord)


def controleer_wachtwoord(opgeslagen_hash: str, wachtwoord: str) -> bool:
    """True als het wachtwoord klopt bij de hash."""
    try:
        return _hasher.verify(opgeslagen_hash, wachtwoord)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_dummy_hash: str | None = None


def controleer_dummy(wachtwoord: str) -> bool:
    """Controleer tegen een vaste nep-hash (altijd False).

    Gebruikt bij een onbekende gebruiker: het inloggen duurt dan even lang als bij
    een bestaande gebruiker, zodat je aan de responstijd niet kunt zien welke
    gebruikersnamen bestaan.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("geen-echt-wachtwoord")
    controleer_wachtwoord(_dummy_hash, wachtwoord)
    return False


def moet_opnieuw_hashen(opgeslagen_hash: str) -> bool:
    """True als de hash met oudere instellingen gemaakt is (dan vernieuwen we hem)."""
    try:
        return _hasher.check_needs_rehash(opgeslagen_hash)
    except InvalidHashError:
        return True


def wachtwoord_fout(wachtwoord: str, herhaling: str | None = None) -> str | None:
    """Controleer een nieuw wachtwoord. Geeft een foutmelding of None als het goed is."""
    if len(wachtwoord) < MINIMALE_LENGTE:
        return f"Het wachtwoord moet minimaal {MINIMALE_LENGTE} tekens lang zijn."
    if herhaling is not None and wachtwoord != herhaling:
        return "De twee wachtwoorden zijn niet gelijk."
    return None
