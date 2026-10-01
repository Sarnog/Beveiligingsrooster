"""Koppeling met de Google Calendar API via een service-account.

Het JSON-sleutelbestand van het service-account staat in de datamap
(google-service-account.json, chmod 600). Het komt nooit in git.

Alle Google-aanroepen lopen via de klasse AgendaKlant. In de tests wordt die
vervangen door een nep-versie, zodat er nooit echt met Google gepraat wordt.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from flask import current_app

from ..models import Dienst, Medewerker
from . import instellingen, klok
from .weekrooster import dagopmerkingen

BESTANDSNAAM = "google-service-account.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
BRON = "beveiligingsrooster"  # markering in extendedProperties.private
TIMEOUT = 30  # seconden
log = logging.getLogger(__name__)
BEHEERD_TEKST = "Automatisch beheerd door Beveiligingsrooster – niet handmatig wijzigen"


class AgendaFout(Exception):
    """Fout bij een Google-aanroep. tijdelijk=True: later opnieuw proberen."""

    def __init__(self, melding: str, tijdelijk: bool = False, status: int | None = None):
        super().__init__(melding)
        self.tijdelijk = tijdelijk
        self.status = status


# ---------------------------------------------------------------------------
# Het sleutelbestand
# ---------------------------------------------------------------------------

def sleutel_pad() -> str:
    return os.path.join(current_app.config["DATA_MAP"], BESTANDSNAAM)


def sleutel_aanwezig() -> bool:
    return os.path.exists(sleutel_pad())


def controleer_sleutel(inhoud: bytes) -> dict:
    """Controleer of een geüpload bestand een service-account-sleutel is."""
    try:
        gegevens = json.loads(inhoud.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as fout:
        raise ValueError("Dit is geen geldig JSON-bestand.") from fout
    if gegevens.get("type") != "service_account" or not gegevens.get("client_email") \
            or not gegevens.get("private_key"):
        raise ValueError("Dit is geen sleutelbestand van een Google service-account.")
    return gegevens


def bewaar_sleutel(inhoud: bytes) -> str:
    """Sla de sleutel op (alleen leesbaar voor de app). Geeft het e-mailadres terug."""
    gegevens = controleer_sleutel(inhoud)
    descriptor = os.open(sleutel_pad(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as bestand:
        bestand.write(inhoud)
    return gegevens["client_email"]


def verwijder_sleutel() -> None:
    if sleutel_aanwezig():
        os.remove(sleutel_pad())


def service_account_email() -> str:
    if not sleutel_aanwezig():
        return ""
    try:
        with open(sleutel_pad(), encoding="utf-8") as bestand:
            return json.load(bestand).get("client_email", "")
    except (OSError, json.JSONDecodeError):
        return ""


# ---------------------------------------------------------------------------
# De klant (dunne laag om google-api-python-client)
# ---------------------------------------------------------------------------

def _vertaal_fout(fout: Exception) -> AgendaFout:
    """Zet een Google-fout om naar een AgendaFout met een Nederlandse melding."""
    from googleapiclient.errors import HttpError

    if isinstance(fout, HttpError):
        status = int(getattr(fout.resp, "status", 0) or 0)
        reden = ""
        try:
            reden = json.loads(fout.content.decode())["error"]["errors"][0].get("reason", "")
        except Exception:  # reden is alleen extra informatie
            reden = ""
        tijdelijk = status == 429 or status >= 500 or reden in (
            "rateLimitExceeded", "userRateLimitExceeded", "backendError")
        meldingen = {
            401: "Google weigert de sleutel (401). Upload het sleutelbestand opnieuw.",
            403: "Geen toegang tot deze agenda (403). Is de agenda gedeeld met het service-account?",
            404: "Agenda of afspraak niet gevonden (404).",
            410: "Afspraak bestaat niet meer (410).",
            409: "Afspraak bestaat al (409).",
            429: "Te veel verzoeken aan Google (429); wordt later opnieuw geprobeerd.",
        }
        melding = meldingen.get(status, f"Google gaf fout {status} {reden}".strip())
        return AgendaFout(melding, tijdelijk=tijdelijk, status=status)
    # Google weigert de sleutel zelf (verwijderd, ingetrokken of verkeerd bestand)
    from google.auth.exceptions import RefreshError, TransportError

    if isinstance(fout, RefreshError):
        tekst = str(fout)
        if "account not found" in tekst or "invalid_grant" in tekst:
            melding = ("Google weigert de sleutel: het service-account of de sleutel bestaat niet "
                       "(meer). Maak in Google Cloud een nieuwe JSON-sleutel en upload die opnieuw.")
        elif "API has not been used" in tekst or "disabled" in tekst:
            melding = "De Google Calendar API staat nog niet aan in het Google Cloud-project."
        else:
            melding = f"Google weigert de sleutel: {tekst}"
        return AgendaFout(melding, tijdelijk=False, status=401)
    if isinstance(fout, (TransportError, TimeoutError, OSError)):
        return AgendaFout("Google is niet bereikbaar (geen internet of time-out). "
                          "Wordt later opnieuw geprobeerd.", tijdelijk=True)
    # Overige fouten: later opnieuw proberen
    return AgendaFout(f"Fout bij Google: {fout}", tijdelijk=True)


class AgendaKlant:
    """Alle Google Calendar-aanroepen die de app gebruikt."""

    def __init__(self, service) -> None:
        self.service = service

    def _voer_uit(self, verzoek):
        naam = getattr(verzoek, "methodId", type(verzoek).__name__)
        try:
            antwoord = verzoek.execute()
        except Exception as fout:  # wordt vertaald
            vertaald = _vertaal_fout(fout)
            log.debug("Google %s mislukt: %s (status %s, tijdelijk %s)", naam, vertaald,
                      vertaald.status, vertaald.tijdelijk)
            raise vertaald from fout
        log.debug("Google %s gelukt", naam)
        return antwoord

    def maak_agenda(self, titel: str, tijdzone: str) -> str:
        agenda = self._voer_uit(self.service.calendars().insert(
            body={"summary": titel, "timeZone": tijdzone}))
        return agenda["id"]

    def deel_agenda(self, agenda_id: str, email: str) -> None:
        """Modus A: de collega leesrechten geven (die krijgt een uitnodiging per e-mail)."""
        self._voer_uit(self.service.acl().insert(
            calendarId=agenda_id, sendNotifications=True,
            body={"role": "reader", "scope": {"type": "user", "value": email}}))

    def agenda_info(self, agenda_id: str) -> dict:
        return self._voer_uit(self.service.calendars().get(calendarId=agenda_id))

    def verwijder_agenda(self, agenda_id: str) -> None:
        self._voer_uit(self.service.calendars().delete(calendarId=agenda_id))

    def maak_afspraak(self, agenda_id: str, body: dict) -> str:
        return self._voer_uit(self.service.events().insert(calendarId=agenda_id, body=body))["id"]

    def wijzig_afspraak(self, agenda_id: str, event_id: str, body: dict) -> str:
        return self._voer_uit(self.service.events().update(
            calendarId=agenda_id, eventId=event_id, body=body))["id"]

    def verwijder_afspraak(self, agenda_id: str, event_id: str) -> None:
        try:
            self._voer_uit(self.service.events().delete(calendarId=agenda_id, eventId=event_id))
        except AgendaFout as fout:
            if fout.status not in (404, 410):  # al weg is ook goed
                raise

    def eigen_afspraken(self, agenda_id: str, van: date | None = None, tot: date | None = None,
                        medewerker_id: int | None = None) -> list[dict]:
        """Alle afspraken die door deze app gemaakt zijn (optioneel binnen een periode).

        Met medewerker_id: alleen de afspraken van die medewerker. Nodig bij een gedeelde
        agenda (modus B), waar meer collega's hun diensten in dezelfde agenda hebben.
        Google accepteert privateExtendedProperty meerdere keren (alle filters gelden).
        """
        filters = [f"bron={BRON}"]
        if medewerker_id is not None:
            filters.append(f"medewerker_id={medewerker_id}")
        afspraken, pagina = [], None
        while True:
            parameters = {"calendarId": agenda_id, "maxResults": 2500, "singleEvents": True,
                          "privateExtendedProperty": filters, "pageToken": pagina}
            if van:
                parameters["timeMin"] = datetime.combine(van, datetime.min.time()).isoformat() + "Z"
            if tot:
                parameters["timeMax"] = datetime.combine(
                    tot + timedelta(days=1), datetime.min.time()).isoformat() + "Z"
            antwoord = self._voer_uit(self.service.events().list(**parameters))
            afspraken.extend(antwoord.get("items", []))
            pagina = antwoord.get("nextPageToken")
            if not pagina:
                return afspraken


def klant() -> AgendaKlant:
    """Maak een verbonden klant met het service-account. In tests vervangen door een nep-klant."""
    if not sleutel_aanwezig():
        raise AgendaFout("Er is nog geen service-account-sleutel geüpload.")
    import google_auth_httplib2
    import httplib2
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    try:
        referenties = service_account.Credentials.from_service_account_file(
            sleutel_pad(), scopes=SCOPES)
    except (ValueError, KeyError) as fout:
        raise AgendaFout("Het sleutelbestand is ongeldig. Upload het JSON-bestand opnieuw.") from fout
    # Maximaal 30 seconden wachten op Google, zodat een pagina nooit blijft hangen
    http = google_auth_httplib2.AuthorizedHttp(referenties, http=httplib2.Http(timeout=TIMEOUT))
    return AgendaKlant(build("calendar", "v3", http=http, cache_discovery=False))


# ---------------------------------------------------------------------------
# Van dienst naar agenda-afspraak
# ---------------------------------------------------------------------------

@dataclass
class Afspraak:
    body: dict


def afspraak_voor(dienst: Dienst | None, dagtekst: str = "") -> Afspraak | None:
    """Bouw de Google-afspraak voor een dienst, of None als er geen afspraak hoort te zijn.

    - Geen dienst, of code met 'zichtbaar in agenda = nee': geen afspraak.
    - Met tijden: afspraak van begin tot eind (eind < begin = volgende dag).
    - Zonder tijden: hele-dag-afspraak als de code dat aangeeft, anders geen.
    """
    if dienst is None:
        return None
    code = dienst.dienstcode
    naam = dienst.dienstnaam
    if not naam:
        return None  # alleen een opmerking, geen dienst
    if code is not None and not code.in_agenda:
        return None

    tijdzone = klok.tijdzone_naam()
    titel = (instellingen.lees("agenda_voorvoegsel") or "") + naam

    regels = []
    if code is not None:
        regels.append(f"Dienstcode: {code.nummer}")
    if dienst.opmerking_tekst:
        opmerking = dienst.opmerking_tekst
        if dienst.opmerking_begin or dienst.opmerking_eind:
            opmerking += f" ({dienst.opmerking_begin or ''}–{dienst.opmerking_eind or ''})"
        regels.append(f"Opmerking: {opmerking}")
    if dagtekst:
        regels.append(f"Dag: {dagtekst}")
    regels.append(BEHEERD_TEKST)

    body = {
        "summary": titel,
        "description": "\n".join(regels),
        "extendedProperties": {"private": {
            "bron": BRON, "dienst_id": str(dienst.id), "medewerker_id": str(dienst.medewerker_id),
        }},
        "reminders": {"useDefault": False},
        "status": "confirmed",  # ook een eerder verwijderde (geannuleerde) afspraak weer tonen
    }

    if dienst.begin and dienst.eind:
        start = datetime.combine(dienst.datum, datetime.strptime(dienst.begin, "%H:%M").time())
        einde = datetime.combine(dienst.datum, datetime.strptime(dienst.eind, "%H:%M").time())
        if einde < start:
            einde += timedelta(days=1)  # nachtdienst: eindigt de volgende dag
        # Lokale tijd + tijdzone: Google regelt zomer-/wintertijd zelf
        body["start"] = {"dateTime": start.isoformat(), "timeZone": tijdzone}
        body["end"] = {"dateTime": einde.isoformat(), "timeZone": tijdzone}
    elif code is not None and code.hele_dag_zonder_tijden:
        body["start"] = {"date": dienst.datum.isoformat()}
        body["end"] = {"date": (dienst.datum + timedelta(days=1)).isoformat()}
    else:
        return None
    return Afspraak(body=body)


def dagtekst_voor(datum: date) -> str:
    return dagopmerkingen([datum])[datum]["tekst"]


def agenda_titel(medewerker: Medewerker) -> str:
    return f"Rooster – {medewerker.naam}"
