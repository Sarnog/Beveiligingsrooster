# API voor een app (versie 1)

Vanaf versie 1.3.0 heeft het Beveiligingsrooster een kleine, stabiele **API om te lezen**. Die is bedoeld voor een latere app (zie [app.md](app.md)) of een eigen script, bijvoorbeeld om je diensten in Home Assistant te tonen.

- Adres: `https://<jouw-server>/api/v1/…`
- Alleen **lezen** (`GET`). Wijzigen via de API kan in deze versie niet (`405`).
- Antwoorden zijn altijd **JSON**, ook bij een fout: `{"fout": "uitleg"}`.
- Het versienummer staat in het pad. Een wijziging die bestaande apps breekt, komt in `/api/v2`; `/api/v1` blijft dan werken. Nieuwe velden kunnen wél worden toegevoegd, dus negeer velden die je niet kent.
- Je ziet precies wat je in de website ziet (dezelfde rechten).
- Antwoorden worden nooit bewaard door een browser of proxy (`Cache-Control: no-store`).
- Een formele beschrijving staat in [openapi.yaml](openapi.yaml) (OpenAPI 3.1).

## Inloggen met een API-token

1. Log in op de website en ga naar je naam rechtsboven → **API-token aanmaken** (of direct naar `/account/tokens`).
2. Geef het token een naam (bijvoorbeeld *Telefoon*) en kies hoe lang het geldig is (30, 90, 180 of 365 dagen).
3. Kopieer het token (`br_…`). **Het wordt maar één keer getoond**: de app bewaart alleen een hash (SHA-256).
4. Stuur het mee in elke aanvraag:

   ```
   Authorization: Bearer br_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

Een token werkt **niet meer** als:
- het verlopen is, of je het intrekt (op dezelfde pagina, knop *Intrekken*);
- je je wachtwoord wijzigt, of de beheerder het reset;
- je account gedeactiveerd of verwijderd wordt, of je rol verandert;
- de beheerder een back-up terugzet.

Het aanmaken en intrekken staat in het logboek. Een token werkt **alleen** voor `/api/v1/…`, niet voor de gewone pagina's.

**Te veel foute tokens:** na 20 onbekende tokens binnen 15 minuten vanaf hetzelfde IP-adres krijgt dat adres 15 minuten lang `429` voor elk onbekend token. Dat staat één keer in het logboek ("API geblokkeerd"). Een geldig token blijft gewoon werken, en een verlopen token of een token dat ongeldig werd door een wachtwoordwijziging telt niet als poging (een app die het blijft proberen, blokkeert zo geen collega's). Foute tokens tellen ook niet mee voor de inlogblokkade van de website.

**CSRF:** met een token is geen CSRF-token nodig (een browser stuurt een `Authorization`-header nooit vanzelf mee). Wie de API vanuit de website gebruikt (met de sessiecookie), moet voor elke niet-`GET`-aanvraag wél de header `X-CSRFToken` meesturen.

> Gebruik de API altijd via **HTTPS** (zie de README: reverse proxy of tunnel). Over gewoon HTTP kan iemand op het netwerk het token meelezen.

## Voorbeelden met curl

```sh
TOKEN=br_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
URL=https://rooster.voorbeeld.nl

curl -s -H "Authorization: Bearer $TOKEN" $URL/api/v1/ik
curl -s -H "Authorization: Bearer $TOKEN" "$URL/api/v1/mijn-rooster?van=2026-10-01&tot=2026-10-31"
curl -s -H "Authorization: Bearer $TOKEN" $URL/api/v1/week/2026/40
curl -s -H "Authorization: Bearer $TOKEN" $URL/api/v1/dienstcodes
```

## Eindpunten

### `GET /api/v1/ik`

Wie ben ik?

```json
{
  "api_versie": 1,
  "app_versie": "1.3.0",
  "gebruiker": {"id": 2, "gebruikersnaam": "collega", "weergavenaam": "Collega", "rol": "gebruiker"},
  "medewerker": {"id": 1, "naam": "Medewerker A", "initialen": "MA"}
}
```

`rol` is `beheerder` of `gebruiker`. `medewerker` is `null` als je account niet aan een medewerker gekoppeld is.

### `GET /api/v1/mijn-rooster?van=JJJJ-MM-DD&tot=JJJJ-MM-DD`

Je eigen diensten. Zonder `van` begint het vandaag; zonder `tot` loopt het 8 weken door. Hooguit 366 dagen per aanvraag. Alleen dagen mét een dienst staan erin.

```json
{
  "medewerker": {"id": 1, "naam": "Medewerker A", "initialen": "MA"},
  "van": "2026-10-01",
  "tot": "2026-11-25",
  "diensten": [
    {
      "datum": "2026-10-01",
      "code": 4,
      "dienstnaam": "VW Vroeg",
      "begin": "07:15",
      "eind": "15:45",
      "uren": 8.0,
      "opmerking": "Locatie A",
      "opmerking_begin": null,
      "opmerking_eind": null,
      "kleur_achtergrond": "#FF0000",
      "kleur_tekst": "#FFFFFF"
    }
  ]
}
```

- `uren` zijn de berekende uren (met toeslag voor zaterdag en zondag), als getal; `null` bij een dienst zonder uren.
- `begin`/`eind` kunnen `null` zijn (bijvoorbeeld *Bapo* zonder tijden). Loopt `eind` vóór `begin`, dan gaat de dienst door na middernacht.

Fouten: `400` bij een ongeldige datum of periode, `404` als je account niet gekoppeld is.

### `GET /api/v1/week/<jaar>/<week>`

Het weekrooster (ISO-week), voor iedereen die ingelogd is, net als de pagina *Weekrooster*.

```json
{
  "jaar": 2026,
  "week": 40,
  "dagen": [
    {"datum": "2026-09-28", "dagopmerking": "", "feestdag": null}
  ],
  "medewerkers": [
    {
      "id": 1, "naam": "Medewerker A", "initialen": "MA",
      "contracturen": 1500.0,
      "weektotaal": 40.0,
      "dagen": [null, {"datum": "2026-09-29", "code": 4, "...": "..."}]
    }
  ]
}
```

`dagen` van een medewerker heeft altijd 7 plaatsen (maandag t/m zondag); `null` = geen dienst. Een week die niet bestaat (bijv. week 53 in een jaar met 52 weken) geeft `404`.

### `GET /api/v1/dienstcodes`

Alle actieve dienstcodes met standaardtijden en kleuren.

```json
{"dienstcodes": [
  {"nummer": 4, "omschrijving": "VW Vroeg", "std_begin": "07:15", "std_eind": "15:45",
   "std_uren": 8.0, "kleur_achtergrond": "#FF0000", "kleur_tekst": "#FFFFFF"}
]}
```

## Statuscodes

| Code | Betekenis |
|---|---|
| `200` | Gelukt |
| `400` | Ongeldige aanvraag (bijv. een verkeerde datum) |
| `401` | Geen of een ongeldig token (verlopen, ingetrokken, wachtwoord gewijzigd) |
| `403` | Geen rechten, of je moet eerst je wachtwoord wijzigen in de website |
| `404` | Niet gevonden |
| `405` | Methode niet toegestaan (de API is alleen-lezen) |
| `429` | Te veel ongeldige tokens vanaf dit adres; wacht 15 minuten |
