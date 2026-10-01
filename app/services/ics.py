"""ICS-feed (iCalendar) per medewerker, als terugvaloptie naast de Google-koppeling.

Tijden worden omgerekend naar UTC (met 'Z'), zodat elke agenda-app zomer- en
wintertijd goed toont zonder dat we een VTIMEZONE-blok hoeven mee te sturen.
"""

from datetime import UTC, datetime, timedelta

from ..models import Dienst, Medewerker
from . import klok
from .google_agenda import afspraak_voor

REGEL_EINDE = "\r\n"


def _escape(tekst: str) -> str:
    """Speciale tekens escapen volgens RFC 5545."""
    return (tekst.replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n"))


def _vouw(regel: str) -> str:
    """Regels langer dan 75 bytes afbreken (RFC 5545 'line folding')."""
    ruw = regel.encode("utf-8")
    if len(ruw) <= 75:
        return regel
    delen, huidig = [], b""
    for teken in regel:
        b = teken.encode("utf-8")
        if len(huidig) + len(b) > (75 if not delen else 74):
            delen.append(huidig.decode("utf-8"))
            huidig = b""
        huidig += b
    delen.append(huidig.decode("utf-8"))
    return (REGEL_EINDE + " ").join(delen)


def _utc(lokaal: str) -> str:
    """'2026-03-02T07:15:00' (lokale tijd) -> '20260302T061500Z'."""
    moment = datetime.fromisoformat(lokaal).replace(tzinfo=klok.tijdzone())
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def maak_feed(medewerker: Medewerker, dagen_terug: int = 30, maanden_vooruit: int = 12) -> str:
    vandaag = klok.vandaag()
    diensten = (
        Dienst.query.filter(Dienst.medewerker_id == medewerker.id,
                            Dienst.datum >= vandaag - timedelta(days=dagen_terug),
                            Dienst.datum <= vandaag + timedelta(days=31 * maanden_vooruit))
        .order_by(Dienst.datum, Dienst.volgnummer).all()
    )
    stempel = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    regels = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Beveiligingsrooster//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape('Rooster – ' + medewerker.naam)}",
        f"X-WR-TIMEZONE:{klok.tijdzone_naam()}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for dienst in diensten:
        afspraak = afspraak_voor(dienst)
        if afspraak is None:
            continue
        body = afspraak.body
        regels += ["BEGIN:VEVENT", f"UID:dienst-{dienst.id}@beveiligingsrooster", f"DTSTAMP:{stempel}"]
        if "dateTime" in body["start"]:
            regels.append(f"DTSTART:{_utc(body['start']['dateTime'])}")
            regels.append(f"DTEND:{_utc(body['end']['dateTime'])}")
        else:
            regels.append(f"DTSTART;VALUE=DATE:{body['start']['date'].replace('-', '')}")
            regels.append(f"DTEND;VALUE=DATE:{body['end']['date'].replace('-', '')}")
        regels.append(f"SUMMARY:{_escape(body['summary'])}")
        regels.append(f"DESCRIPTION:{_escape(body['description'])}")
        regels.append("TRANSP:OPAQUE")
        regels.append("END:VEVENT")
    regels.append("END:VCALENDAR")
    return REGEL_EINDE.join(_vouw(r) for r in regels) + REGEL_EINDE
