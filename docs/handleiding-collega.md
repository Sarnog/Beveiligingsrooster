# Handleiding voor collega's (versie 1.6.0)

Met het Beveiligingsrooster bekijk je je diensten, het weekrooster van het team en je uren. Je kunt niets wijzigen; dat doet de planner.

## Inloggen

1. Open het adres dat je van de planner hebt gekregen, bijvoorbeeld `https://rooster.voorbeeld.nl`.
2. Log in met je gebruikersnaam en het tijdelijke wachtwoord.
3. Kies bij de eerste keer een **eigen wachtwoord** van minimaal 10 tekens.

Wachtwoord vergeten? Vraag de planner om een reset. Na 5 verkeerde pogingen moet je 15 minuten wachten.

## Wat zie je?

| Menu | Wat |
|---|---|
| **Mijn rooster** | bovenaan je dienst van **vandaag** en je **volgende dienst**, daaronder per dag een kaart met je diensten voor de komende 8 weken (alleen als je account aan jou als medewerker is gekoppeld) |
| **Kalender** | het hele jaar. Klik op een week of dag om het weekrooster te openen. Kleuren: oranje = vandaag, geel = feestdag, blauw = vakantie, groen = weekend |
| **Weekrooster** | de hele week van het team, met dienst, tijden en uren per dag |
| **Urenoverzicht** | de weektotalen van iedereen, per week |
| **Zoeken** | zoek diensten op naam, initialen of dienstcode |

Wijkt een tijd af van de standaardtijd van die dienst, dan zie je dat als je er met de muis op staat (*Handmatig aangepast*).

Heb je op een dag **twee diensten**, dan staan ze in het weekrooster **onder elkaar** in je blok: de eerste bovenaan, de tweede onderaan (elk met eigen dienstnaam, tijden en uren). Een opmerking van die dag staat dan achter de naam van de eerste dienst. In *Mijn rooster* staan ze als twee regels; de tweede heeft *(2e dienst)* achter de datum. In je agenda (ICS of Google Agenda) worden het twee afspraken.

### Licht of donker

Rechtsboven, vóór je naam, staat een schakelaar met een ☀️ zon en een 🌙 maan. Klik erop om te
wisselen tussen het lichte en het donkere thema. Je keuze wordt bij je account bewaard: na opnieuw
inloggen (ook op een ander apparaat) staat hij nog hetzelfde. Heb je nog niets gekozen, dan volgt de
app de instelling van je apparaat. Op de telefoon zit de schakelaar in het menu (☰).

## Printen en exporteren

- **Printen**: klik in het weekrooster op **Printen**. De week komt liggend op één A4, opgemaakt als het papieren rooster (per medewerker een blok, de uren in de grijze kolom naast elke dag, rechts het weektotaal). Staan de kleuren er niet op, zet dan in het printvenster "Achtergrondafbeeldingen afdrukken" aan.
- **Exporteren**: in het urenoverzicht en bij zoekresultaten staat een knop **Exporteren (CSV)**. Dat bestand opent in Excel.
- **Excel-bestand (`.xlsx`)**: sinds versie 1.6.0 maakt alleen de planner een Excel-export (in Beheer). De knoppen *Exporteren (Excel)* en *Meer exportkeuzes…* zijn voor collega's verdwenen. Heb je een Excel-bestand van het rooster nodig, vraag het dan aan de planner. De CSV-export werkt gewoon.

## Op je telefoon

De app is gemaakt voor de telefoon: je hoeft niet in te zoomen of opzij te schuiven.

- **Menu:** tik op ☰ rechtsboven.
- **Mijn rooster:** bovenaan *Vandaag* en *Volgende dienst*. Met de grote knop **📅 Toevoegen aan mijn agenda** zet je je diensten in de agenda van je telefoon (zie hieronder).
- **Weekrooster:** kies bovenaan **Per dag** (één dag, het hele team) of **Per medewerker** (één collega, zeven dagen). Blader met ◀ ▶, kies uit de lijst, of veeg naar links en rechts. Bij *Per medewerker* begin je bij jezelf. Je keuze wordt onthouden.
- Liever het gewone rooster (het "Excel-raster")? Tik op **Rasterweergave**; op een tablet ga je met **Telefoonweergave** weer terug.
- Brede tabellen (zoals het urenoverzicht) kun je binnen de tabel opzij vegen; de eerste kolom blijft staan.
- **Printen** vanaf je telefoon geeft gewoon het hele weekrooster, liggend op één A4.

### Als app op je beginscherm

Werkt de site via **https://**, dan kun je hem als app installeren. Hij opent dan zonder adresbalk, met een eigen icoon.

- **Android (Chrome):** menu ⋮ → **App installeren** (of *Toevoegen aan startscherm*).
- **iPhone (Safari):** deelknop (vierkantje met pijl) → **Zet op beginscherm**.

Het rooster wordt niet op je telefoon bewaard: je ziet altijd de nieuwste versie. Zonder internet zie je de melding *Je bent offline*.

## Je diensten in je eigen agenda

Dit wordt ingesteld door de planner. Tik in **Mijn rooster** op **Toevoegen aan mijn agenda**: heeft de planner een abonnementslink voor je gemaakt, dan opent je agenda-app direct. Onder *Hoe werkt dat?* zie je wat er voor jou is ingesteld.

- **Google Agenda**: je krijgt een uitnodiging voor een agenda "Rooster – jouw naam". Accepteer die, dan staan je diensten automatisch in je agenda. Wijzigingen verschijnen binnen ongeveer een minuut.
- **Andere agenda's** (Outlook, Apple): de planner kan je een geheime abonnementslink (ICS) geven. Let op: Google ververst zo'n link maar een paar keer per dag.

## Een app koppelen (API-token)

Wil je je rooster in een andere app of een eigen script gebruiken (bijvoorbeeld Home Assistant)? Klik op je naam rechtsboven → **API-token**. Je krijgt een token dat je **één keer** ziet; kopieer het meteen. Het werkt niet meer na de verloopdatum, na *Intrekken*, of als je je wachtwoord wijzigt. Uitleg voor ontwikkelaars: [api.md](api.md).
