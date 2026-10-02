# Google Agenda koppelen

Met deze koppeling komen de diensten van een collega automatisch in zijn of haar eigen Google Agenda. Een wijziging door de planner staat er binnen ongeveer een minuut in.

Het werkt met een **service-account**. Dat is een soort "robotaccount" van Google, speciaal voor de app. Je maakt het één keer aan. Daarna stel je per medewerker de koppeling in.

> De app heeft alleen **uitgaand** internet nodig (naar Google). Je hoeft geen poorten open te zetten.

---

## Deel 1: service-account aanmaken (één keer, ongeveer 10 minuten)

Je hebt een Google-account nodig (een gewoon Gmail-account is prima).

### Stap 1: project aanmaken

1. Ga naar <https://console.cloud.google.com/> en log in.
2. Klik bovenaan op de projectkiezer en daarna op **Nieuw project**.
3. Naam: bijvoorbeeld `beveiligingsrooster`. Klik op **Maken**.
4. Kies het nieuwe project in de projectkiezer.

<!-- Screenshot: nieuw project (placeholder) -->

### Stap 2: Calendar API aanzetten

1. Ga naar **API's en services → Bibliotheek**.
2. Zoek **Google Calendar API** en klik op **Inschakelen**.

<!-- Screenshot: Google Calendar API inschakelen (placeholder) -->

### Stap 3: service-account maken

1. Ga naar **IAM en beheer → Serviceaccounts**.
2. Klik op **Serviceaccount maken**.
3. Naam: bijvoorbeeld `rooster`. Klik op **Maken en doorgaan**.
4. Rollen zijn niet nodig: klik op **Doorgaan** en **Klaar**.

<!-- Screenshot: service-account maken (placeholder) -->

### Stap 4: sleutel downloaden

1. Klik op het nieuwe service-account en ga naar het tabblad **Sleutels**.
2. Klik op **Sleutel toevoegen → Nieuwe sleutel maken → JSON → Maken**.
3. Er wordt een `.json`-bestand gedownload.

**Bewaar dit bestand goed en deel het met niemand.** Wie het heeft, kan de agenda's van het rooster aanpassen. Zet het nooit in git en niet in een gedeelde map.

> Zie je de melding *"Het maken van serviceaccountsleutels is uitgeschakeld"*? Dan blokkeert een organisatiebeleid dat. Bij een gewoon Gmail-account komt dit niet voor. Bij Google Workspace moet een beheerder het beleid `iam.disableServiceAccountKeyCreation` uitzetten.

### Stap 5: sleutel uploaden in de app

1. Log in als beheerder en ga naar **Beheer → Google Agenda**.
2. Kies bij **1. Service-account** het JSON-bestand en klik op **Uploaden**.
3. Je ziet nu het e-mailadres van het service-account, bijvoorbeeld `rooster@beveiligingsrooster.iam.gserviceaccount.com`.

De app slaat de sleutel op in de datamap (`data/google-service-account.json`), alleen leesbaar voor de app zelf. Hij staat daarmee ook in back-ups van `data/`. Bewaar die back-ups dus veilig.

Verwijder daarna het gedownloade bestand van je computer (of bewaar het in een wachtwoordkluis).

---

## Deel 2: medewerkers koppelen

Kies per medewerker een van de twee modi. Het e-mailadres (Google-account) van de collega kun je direct bij de knop van modus A invullen; het wordt ook bij de medewerker opgeslagen. Na een Excel-import zijn die e-mailadressen nog leeg.

### Modus A (aanbevolen): de app maakt een eigen agenda

Vul bij de medewerker het e-mailadres in en klik op **Modus A: eigen agenda aanmaken**. De knop toont even "Bezig…". Daarna gebeurt het volgende:

1. De app maakt een agenda **"Rooster – naam"** aan.
2. De app deelt die agenda (alleen lezen) met het e-mailadres van de collega.
3. De collega krijgt een uitnodiging per e-mail. Na **accepteren** staat de agenda naast de eigen agenda's, en krijgt hij of zij er een eigen kleur voor.
4. De app vult de agenda direct met alle diensten.

De collega hoeft verder niets te doen.

<!-- Screenshot: uitnodiging voor gedeelde agenda (placeholder) -->

### Modus B: de collega deelt een bestaande agenda

Handig als iemand de diensten in een agenda wil die hij of zij al heeft.

1. De collega opent Google Agenda op de computer: ⚙ **Instellingen** → kies de agenda → **Delen met specifieke personen of groepen** → **Personen toevoegen**.
2. Vul het **e-mailadres van het service-account** in. De beheerder ziet dat in *Beheer → Google Agenda* en kan het met de knop **Kopiëren** kopiëren.
3. Kies het recht **"Wijzigingen aanbrengen in afspraken"** en klik op **Verzenden**.
4. Op dezelfde instellingenpagina staat onder **Agenda integreren** het **Agenda-ID**, bijvoorbeeld `abc123@group.calendar.google.com`. Voor de hoofdagenda is dat het e-mailadres zelf.
5. De beheerder klikt bij de medewerker op **Modus B: gedeelde agenda**, vult het agenda-ID in en klikt op **Koppelen**. De app test direct of de agenda bereikbaar is.

---

## Wat komt er in de agenda?

- **Eén afspraak per dienst:**
  - de titel is de dienstnaam, bijvoorbeeld "VW Vroeg", eventueel met een voorvoegsel (*Instellingen → Agenda*);
  - de tijden zijn de echte tijden van de dienst, inclusief handmatige aanpassingen;
  - een nachtdienst (eindtijd vóór de begintijd) eindigt de volgende dag, ook in de nacht van de klokwissel.
- **De omschrijving** bevat:
  - de dienstcode;
  - de opmerking;
  - de dagopmerking (bijvoorbeeld een vakantie);
  - de tekst *"Automatisch beheerd door Beveiligingsrooster – niet handmatig wijzigen"*.
- **Een dienst zonder tijden** (bijvoorbeeld Bapo) wordt een hele-dag-afspraak als dat bij de dienstcode aan staat. Anders komt er geen afspraak.
- **Geen afspraak** komt er bij:
  - een lege cel;
  - de blanco-code;
  - een code met "zichtbaar in agenda = nee".

  Bestond er al een afspraak, dan wordt die verwijderd.
- **De app raakt alleen haar eigen afspraken aan.** Die herkent ze aan een verborgen markering. Afspraken die de collega zelf maakt, blijven altijd staan.
- **Gedeelde agenda (modus B) met meer collega's:** de markering bevat ook de medewerker. Volledig synchroniseren of ontkoppelen van één collega raakt alleen diens eigen afspraken; die van de andere collega's in dezelfde agenda blijven staan.

## Hoe snel?

Een roosterwijziging komt in een wachtrij. De worker verwerkt die na ongeveer 10 seconden. Snel achter elkaar wijzigen levert daardoor maar één update op. Meestal staat de wijziging binnen een minuut in de agenda. De Google-app op de telefoon kan soms nog iets later verversen.

## Knoppen per medewerker

| Knop | Wat |
|---|---|
| Test koppeling | controleert direct of de agenda bereikbaar is |
| Volledig synchroniseren | maakt de agenda gelijk aan het rooster, van 7 dagen terug tot 12 maanden vooruit (instelbaar), en ruimt verweesde afspraken op |
| Ontkoppelen… | stopt de koppeling. Je kiest of de afspraken blijven staan of verwijderd worden. Bij modus A wordt dan de hele agenda verwijderd, bij modus B alleen de afspraken van deze medewerker |

De status toont:
- wanneer er het laatst is gesynchroniseerd;
- hoeveel afspraken er zijn;
- de laatste fout, als die er is.

## Fouten

- **Google-limiet.** Google laat één service-account maar een beperkt aantal wijzigingen in korte tijd doen. Alle agenda's van modus A horen bij hetzelfde service-account, dus collega's delen die limiet. Daarom:
  - stuurt de app maximaal één wijziging per seconde naar Google (een heel jaarrooster duurt per collega dus een paar minuten);
  - slaat **Volledig synchroniseren** afspraken over die al goed staan;
  - pauzeert de app bij een limietmelding van Google (`quotaExceeded`, `rateLimitExceeded`) de **hele** wachtrij 30 minuten en gaat daarna vanzelf verder. Op *Beheer → Google Agenda* zie je tot hoe laat. Taken gaan daarbij niet verloren en tellen niet als mislukt. Met **Mislukte opnieuw proberen** hef je de pauze meteen op.
- **Tijdelijke fouten** (Google is druk, of er is geen internet) worden automatisch opnieuw geprobeerd, steeds met langere pauzes: 30 seconden, 1 minuut, 2 minuten, en zo verder tot maximaal 1 uur.
- **Na 6 mislukte pogingen**, of bij een blijvende fout (bijvoorbeeld geen toegang), gebeurt het volgende:
  - de fout komt bij de medewerker te staan;
  - de fout komt in het **logboek** ("Agenda-sync fout").

  Met **Mislukte opnieuw proberen** zet je deze taken terug in de wachtrij.

| Melding | Oplossing |
|---|---|
| Geen toegang tot deze agenda (403 …) | Modus A: staat de sleutel van **hetzelfde** service-account erin als toen de agenda werd aangemaakt? Zo niet: zet de oude sleutel terug, of ontkoppel en maak de agenda opnieuw aan. Modus B: is de agenda gedeeld met het service-account, met het recht "Wijzigingen aanbrengen"? |
| Google-limiet bereikt (403 quotaExceeded) | Geen actie nodig: de app pauzeert en gaat vanzelf verder. Gebeurt het vaak? Gebruik dan niet steeds *Volledig synchroniseren*. |
| Agenda niet gevonden (404) | Klopt het agenda-ID? Is de agenda verwijderd? Ontkoppel en koppel opnieuw. |
| Google weigert de sleutel (401) | Is de sleutel ingetrokken in Google Cloud? Upload een nieuwe sleutel. |
| Er is nog geen service-account-sleutel geüpload | Zie deel 1, stap 5. |
| Google weigert de sleutel: het service-account of de sleutel bestaat niet (meer) | De sleutel of het service-account is verwijderd, of het is een verkeerd bestand. Maak in Google Cloud een nieuwe JSON-sleutel (deel 1, stap 4) en upload die opnieuw. |
| De Google Calendar API staat nog niet aan | Zet de API aan (deel 1, stap 2) en wacht een paar minuten. |
| Google is niet bereikbaar | De LXC heeft geen internet (DNS, firewall, proxy). De app wacht maximaal 30 seconden en probeert synchronisaties later opnieuw. |

---

## Alternatief: ICS-feed (voor Outlook, Apple en anderen)

Klik in *Beheer → Google Agenda* bij een medewerker op **ICS-link maken**. Je krijgt een geheime link `https://…/ics/<token>.ics`. De collega kan die ook zelf vinden onder **Mijn rooster → In mijn agenda**. De link werkt in elke agenda-app die abonnementen ondersteunt.

Nadelen:
- **Google Agenda ververst een geabonneerde feed maar enkele keren per dag.** Voor directe updates gebruik je modus A of B.
- De app moet **via internet bereikbaar** zijn, want de agenda-app van de collega haalt de feed zelf op. Zie *HTTPS en bereikbaarheid* in [proxmox-lxc.md](proxmox-lxc.md).
- Iedereen met de link ziet de diensten. Een link die uitgelekt is, maak je ongeldig met **Vernieuwen** of **Intrekken**.
