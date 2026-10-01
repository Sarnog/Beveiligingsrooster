"""De dunne laag om de Google Calendar API (AgendaKlant) en het vertalen van fouten.

Er wordt nooit echt met Google gepraat: een nep-'service' doet alsof.
"""

import json
import os

import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.services import google_agenda
from app.services.google_agenda import AgendaFout, AgendaKlant, _vertaal_fout


def http_fout(status: int, reden: str = "") -> HttpError:
    inhoud = json.dumps({"error": {"errors": [{"reason": reden}]}}).encode() if reden else b"x"
    return HttpError(Response({"status": status}), inhoud)


# ---------- Fouten vertalen ----------

@pytest.mark.parametrize("status, tijdelijk, tekst", [
    (401, False, "weigert de sleutel"),
    (403, False, "Geen toegang"),
    (404, False, "niet gevonden"),
    (410, False, "bestaat niet meer"),
    (429, True, "Te veel verzoeken"),
    (500, True, "500"),
    (503, True, "503"),
    (400, False, "400"),
])
def test_http_fouten(status, tijdelijk, tekst):
    fout = _vertaal_fout(http_fout(status))
    assert isinstance(fout, AgendaFout) and fout.status == status
    assert fout.tijdelijk is tijdelijk and tekst in str(fout)


def test_403_met_snelheidslimiet_is_tijdelijk():
    fout = _vertaal_fout(http_fout(403, "rateLimitExceeded"))
    assert fout.tijdelijk and fout.status == 403


@pytest.mark.parametrize("tekst, verwacht", [
    ("invalid_grant: account not found", "bestaat niet"),
    ("Calendar API has not been used in project", "Calendar API staat nog niet aan"),
    ("iets anders", "Google weigert de sleutel: iets anders"),
])
def test_refresh_fouten_zijn_blijvend(tekst, verwacht):
    fout = _vertaal_fout(RefreshError(tekst))
    assert verwacht in str(fout) and not fout.tijdelijk and fout.status == 401


@pytest.mark.parametrize("oorzaak", [TransportError("weg"), TimeoutError(), ConnectionResetError(),
                                     OSError("netwerk")])
def test_netwerk_en_timeouts_zijn_tijdelijk(oorzaak):
    fout = _vertaal_fout(oorzaak)
    assert fout.tijdelijk and "niet bereikbaar" in str(fout)


def test_onbekende_fout_is_tijdelijk():
    fout = _vertaal_fout(ValueError("raar"))
    assert fout.tijdelijk and "raar" in str(fout)


# ---------- AgendaKlant met een nep-service ----------

class Verzoek:
    def __init__(self, antwoord):
        self.antwoord = antwoord

    def execute(self):
        if isinstance(self.antwoord, Exception):
            raise self.antwoord
        return self.antwoord


class NepService:
    """Bootst service.calendars()/acl()/events() na en onthoudt alle aanroepen."""

    def __init__(self, antwoorden: dict):
        self.antwoorden = antwoorden
        self.aanroepen: list[tuple[str, dict]] = []

    def _groep(self, naam):
        service = self

        class Groep:
            def __getattr__(self, methode):
                def aanroep(**kwargs):
                    service.aanroepen.append((f"{naam}.{methode}", kwargs))
                    antwoord = service.antwoorden.get(f"{naam}.{methode}", {})
                    if isinstance(antwoord, list):
                        antwoord = antwoord.pop(0)
                    return Verzoek(antwoord)
                return aanroep

        return Groep()

    def calendars(self):
        return self._groep("calendars")

    def acl(self):
        return self._groep("acl")

    def events(self):
        return self._groep("events")


def test_agenda_aanroepen():
    service = NepService({"calendars.insert": {"id": "agenda1"}, "calendars.get": {"summary": "S"},
                          "events.insert": {"id": "e1"}, "events.update": {"id": "e1"}})
    klant = AgendaKlant(service)
    assert klant.maak_agenda("Rooster", "Europe/Amsterdam") == "agenda1"
    klant.deel_agenda("agenda1", "a@voorbeeld.nl")
    assert klant.agenda_info("agenda1") == {"summary": "S"}
    assert klant.maak_afspraak("agenda1", {"summary": "x"}) == "e1"
    assert klant.wijzig_afspraak("agenda1", "e1", {"summary": "y"}) == "e1"
    klant.verwijder_afspraak("agenda1", "e1")
    klant.verwijder_agenda("agenda1")
    namen = [naam for naam, _ in service.aanroepen]
    assert namen == ["calendars.insert", "acl.insert", "calendars.get", "events.insert",
                     "events.update", "events.delete", "calendars.delete"]
    acl = service.aanroepen[1][1]
    assert acl["body"] == {"role": "reader", "scope": {"type": "user", "value": "a@voorbeeld.nl"}}


def test_verwijderen_van_verdwenen_afspraak_is_goed():
    klant = AgendaKlant(NepService({"events.delete": [http_fout(404), http_fout(410), http_fout(500)]}))
    klant.verwijder_afspraak("a", "weg")
    klant.verwijder_afspraak("a", "weg")
    with pytest.raises(AgendaFout) as fout:
        klant.verwijder_afspraak("a", "kapot")
    assert fout.value.tijdelijk


def test_eigen_afspraken_met_filters_en_paginas():
    from datetime import date

    service = NepService({"events.list": [{"items": [{"id": "1"}], "nextPageToken": "p2"},
                                          {"items": [{"id": "2"}]}]})
    afspraken = AgendaKlant(service).eigen_afspraken("team", date(2026, 3, 1), date(2026, 3, 31),
                                                     medewerker_id=7)
    assert [a["id"] for a in afspraken] == ["1", "2"]
    eerste, tweede = (kwargs for _, kwargs in service.aanroepen)
    assert eerste["privateExtendedProperty"] == ["bron=beveiligingsrooster", "medewerker_id=7"]
    assert eerste["timeMin"] == "2026-03-01T00:00:00Z" and eerste["timeMax"] == "2026-04-01T00:00:00Z"
    assert eerste["pageToken"] is None and tweede["pageToken"] == "p2"


def test_eigen_afspraken_zonder_medewerker_filter():
    service = NepService({"events.list": {"items": []}})
    AgendaKlant(service).eigen_afspraken("a")
    kwargs = service.aanroepen[0][1]
    assert kwargs["privateExtendedProperty"] == ["bron=beveiligingsrooster"] and "timeMin" not in kwargs


# ---------- Sleutelbestand ----------

def test_sleutel_controles(app):
    with pytest.raises(ValueError, match="geen geldig JSON"):
        google_agenda.controleer_sleutel(b"\xff\xfe")
    with pytest.raises(ValueError, match="service-account"):
        google_agenda.controleer_sleutel(b'{"type": "service_account"}')
    assert google_agenda.service_account_email() == ""
    with pytest.raises(AgendaFout, match="nog geen"):
        google_agenda.klant()


def test_kapot_sleutelbestand(app):
    with open(google_agenda.sleutel_pad(), "w", encoding="utf-8") as bestand:
        bestand.write("{kapot")
    assert google_agenda.service_account_email() == ""
    with open(google_agenda.sleutel_pad(), "w", encoding="utf-8") as bestand:
        json.dump({"type": "service_account", "client_email": "x@y", "private_key": "geen"}, bestand)
    assert google_agenda.service_account_email() == "x@y"
    with pytest.raises(AgendaFout, match="ongeldig"):
        google_agenda.klant()
    google_agenda.verwijder_sleutel()
    assert not os.path.exists(google_agenda.sleutel_pad())
    google_agenda.verwijder_sleutel()  # nogmaals: geen fout
