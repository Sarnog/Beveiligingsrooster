"""Toegangslog van Gunicorn zonder geheime tokens.

De ICS-feed (/ics/<token>.ics) en de deellink (/deel/<token>/...) hebben een geheim
token in het adres. Wie de log van de container kan lezen, zou daarmee het rooster
kunnen opvragen. Deze logger vervangt die tokens door '***' (in het pad, de
verzoekregel én de Referer). Ingesteld in docker/gunicorn.conf.py (logger_class).
"""

import re

from gunicorn.glogging import Logger

_TOKEN = re.compile(r"(/(?:ics|deel)/)[^/?\s.\"]+")


def maskeer_tokens(tekst: str) -> str:
    """'/ics/abc123.ics' -> '/ics/***.ics' en '/deel/abc123/week' -> '/deel/***/week'."""
    return _TOKEN.sub(r"\1***", tekst)


class ToegangsLogger(Logger):
    """Gunicorn-logger die tokens in alle velden van de toegangslog maskeert."""

    def atoms(self, resp, req, environ, request_time):
        atomen = super().atoms(resp, req, environ, request_time)
        return {sleutel: maskeer_tokens(waarde) if isinstance(waarde, str) else waarde
                for sleutel, waarde in atomen.items()}
