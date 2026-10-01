"""Configuratie van de app.

Alle instellingen komen uit omgevingsvariabelen (in Docker: docker-compose.yml
of het .env-bestand ernaast). Zo staan er nooit geheimen in de repository.
Zonder SECRET_KEY maakt de app zelf een geheime sleutel aan in de datamap.
"""

import os
from datetime import timedelta


def _bool(waarde: str | None, standaard: bool = False) -> bool:
    """Zet tekst als '1', 'ja', 'true' om naar True."""
    if waarde is None:
        return standaard
    return waarde.strip().lower() in ("1", "ja", "true", "yes", "aan")


class Config:
    """Standaardconfiguratie, gevuld vanuit de omgeving."""

    def __init__(self) -> None:
        # Map waar database, back-ups en het service-account-bestand staan
        self.DATA_MAP = os.environ.get("DATA_MAP", os.path.abspath("data"))

        # Geheime sleutel voor sessies (leeg = automatisch aangemaakt in de datamap)
        self.SECRET_KEY = os.environ.get("SECRET_KEY", "")

        # SQLite-database in de datamap (tenzij expliciet anders opgegeven)
        self.SQLALCHEMY_DATABASE_URI = os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(self.DATA_MAP, "rooster.db"),
        )
        self.SQLALCHEMY_TRACK_MODIFICATIONS = False

        # Openbaar adres van de app, bijvoorbeeld https://rooster.voorbeeld.nl
        self.BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

        # Achter een reverse proxy (Caddy/tunnel) de X-Forwarded-headers vertrouwen
        self.PROXY_VERTROUWEN = _bool(os.environ.get("PROXY_VERTROUWEN"))

        # Sessiecookies: altijd HttpOnly en SameSite=Lax; Secure bij HTTPS
        # (COOKIE_SECURE=1/0 overschrijft de keuze op basis van BASE_URL).
        # Er is geen 'ingelogd blijven'-cookie: de sessie duurt SESSIE_UREN.
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = _bool(
            os.environ.get("COOKIE_SECURE"), self.BASE_URL.startswith("https://")
        )

        # Hoe lang een sessie geldig blijft (in uren)
        sessie_uren = int(os.environ.get("SESSIE_UREN", "12"))
        self.PERMANENT_SESSION_LIFETIME = timedelta(hours=sessie_uren)

        # CSRF-token blijft even lang geldig als de sessie
        self.WTF_CSRF_TIME_LIMIT = None

        # Maximale uploadgrootte (Excel-import, back-up terugzetten): 50 MB
        self.MAX_CONTENT_LENGTH = 50 * 1024 * 1024

        # Logging (zie app/debuglog.py): niveau van de console en het debuglog-bestand
        niveau = os.environ.get("LOG_NIVEAU", "INFO").strip().upper()
        self.LOG_NIVEAU = niveau if niveau in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO"
        self.DEBUG_LOG = _bool(os.environ.get("DEBUG_LOG"))

        self.TESTING = False
