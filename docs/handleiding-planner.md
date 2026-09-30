# Handleiding voor de planner (beheerder)

Deze handleiding is voor wie het rooster invult. Als beheerder mag je alles; collega's met de rol *gebruiker* kunnen alleen kijken, printen en exporteren.

<!-- Screenshot: weekrooster met code-raster (placeholder) -->

## 1. Een week invullen met het code-raster

Open **Weekrooster** (of klik in de **Kalender** op een weeknummer). Rechts van het rooster staat het **code-raster**: per medewerker één rij (initialen) en zeven kolommen MA t/m ZO. Op een smal scherm staat het code-raster onder het rooster.

1. Klik op een cel in het code-raster.
2. Typ het **nummer van de dienstcode**, bijvoorbeeld `4`, en druk op **Tab** (volgende dag) of **Enter** (volgende medewerker).
3. Direct gebeurt het volgende:
   - de dienstnaam verschijnt in het rooster, in de kleur van de code;
   - de standaard begin- en eindtijd van die code worden ingevuld;
   - de uren van die dag en het weektotaal worden berekend.

### Opslaan

Wijzigingen worden **niet** meteen opgeslagen. Wat je typt, zie je wel direct terug: de dienstnaam, de tijden en de uren worden al uitgerekend. Maar de gegevens worden pas bewaard als je op **Opslaan** klikt of **Ctrl+S** drukt. Zo richt een per ongeluk getypte waarde geen schade aan.

Zolang er iets niet is opgeslagen:
- hebben gewijzigde cellen een **oranje hoekje** en een oranje streep onderaan;
- staat er boven het code-raster "*N wijzigingen nog niet opgeslagen*";
- toont de knop het aantal, bijvoorbeeld **Opslaan (3)**.

Je kunt gewoon meerdere cellen achter elkaar wijzigen en dan één keer opslaan.

Wil je de pagina verlaten zonder op te slaan, bijvoorbeeld via het menu, een andere week, de weekkiezer of Uitloggen? Dan vraagt de app eerst wat je wilt:

| Knop | Wat gebeurt er |
|---|---|
| **Opslaan** | alles opslaan en daarna verder naar waar je heen wilde |
| **Terug** | terug naar het rooster om verder te wijzigen |
| **Doorgaan** | verder zonder opslaan: alle wijzigingen gaan verloren |

Sluit of ververs je de browser (of het tabblad) met niet-opgeslagen wijzigingen, dan toont de browser zijn eigen vraag ("Pagina verlaten?"). Browsers staan daar geen eigen knoppen toe, dus daar kun je alleen kiezen tussen blijven en verlaten.

Klikken in het rooster, printen en de uitklapbare lijsten (Dienstcodes, Toetsen) geven geen vraag.

| Wat je typt | Betekenis |
|---|---|
| een codenummer (`1`, `4`, `17`, …) | die dienst |
| niets (cel leeg maken met **Delete**) | geen dienst |
| de blanco-code (standaard `15`) | ook: geen dienst (voor wie gewend is aan Excel) |
| een onbekend nummer | rode cel met de melding "Onbekende dienstcode"; er wordt niets opgeslagen |

### Toetsen (zoals in Excel)

| Toets | Wat gebeurt er |
|---|---|
| Pijltjes, Tab / Shift+Tab, Enter / Shift+Enter | verplaatsen |
| Direct typen | cel overschrijven |
| F2 of dubbelklik | bestaande waarde bewerken |
| Esc | bewerken annuleren |
| Delete / Backspace | geselecteerde cellen leegmaken |
| Shift + pijltjes of Shift + klik | een blok cellen selecteren |
| Ctrl+C / Ctrl+V | kopiëren en plakken, ook een blok dat je in Excel hebt gekopieerd |
| Ctrl+Z | de laatste niet-opgeslagen wijziging(en) ongedaan maken |
| Ctrl+S | opslaan |

Plakken van één waarde terwijl een blok geselecteerd is, vult het hele blok (handig om een hele rij `4` te geven).

## 2. Tijden handmatig aanpassen

Wijkt een dienst af van de standaardtijden? Klik dan in het **rooster zelf** op de begin- of eindtijd (onderste regel van het blok) en typ de nieuwe tijd. Tijden mag je invoeren als `715`, `7:15`, `07.15` of `0715`; ze worden altijd `07:15`.

- De uren worden opnieuw berekend.
- Een handmatige tijd is **rood gestippeld onderstreept** met een klein rood hoekje. Hij blijft staan tot je de **dienstcode opnieuw wijzigt**; dan komen de standaardtijden van de nieuwe code terug.

### Vrije dienst en eigen uren

Niet elke dienst heeft een code. Bijvoorbeeld een cursus of een extra ronde.

- Typ in het rooster op de **dienstnaamregel** (regel c) een eigen naam. Een eventuele code vervalt dan.
- Typ in de **urencel** (rechts van de eindtijd) zelf het aantal uren, bijvoorbeeld `8` of `7,5`. Zelf ingevulde uren:
  - gaan voor de berekening;
  - krijgen geen weekendtoeslag;
  - hebben dezelfde rode markering.
- **Delete** op de urencel zet de uren weer op automatisch.
- Een nieuwe dienstcode invoeren maakt de uren ook weer automatisch.

## 3. Opmerkingen

Elk medewerkerblok heeft vier regels per dag:

| Regel | Inhoud | Telt mee in uren? |
|---|---|---|
| a | opmerking (bijvoorbeeld "BV", "BHV", "Later op dienst") | nee |
| b | begin- en eindtijd bij de opmerking (bijvoorbeeld BV 13:30–15:45) | nee (instelbaar bij Instellingen) |
| c | dienstnaam (komt van de dienstcode) | – |
| d | begin, eind en uren van de dienst | **ja** |

Een opmerking die precies overeenkomt met een **kleurregel** (bijvoorbeeld een locatienaam) krijgt automatisch de kleur van die regel (*Beheer → Dienstcodes → Opmerking-kleurregels*).

**Dagopmerking** (de balk onder de datums): wordt automatisch gevuld met feestdagen en vakanties. Een feestdag gaat voor een vakantie, en vakanties staan alleen op werkdagen. Je kunt de tekst overschrijven:

- **Typen**: eigen tekst.
- **Delete** op een eigen tekst: de automatische tekst komt terug.
- **Delete** op een automatische tekst: de dagopmerking wordt verborgen.

## 4. Week kopiëren

Klik op **Week kopiëren naar…**, kies de doelweek en of je de hele week of één medewerker wilt kopiëren. De doelweek wordt **gelijk gemaakt** aan deze week: daar bestaande diensten worden overschreven.

## 5. Printen

Klik op **Printen**. De week komt liggend op één A4 (ook bij meer medewerkers: de print schaalt zelf mee, bij een groot team wordt de letter kleiner), zonder het code-raster en met kleuren. Kies in het printvenster eventueel "Achtergrondafbeeldingen afdrukken" als de kleuren ontbreken.

## 6. Kalender, overzichten en zoeken

- **Kalender** is de jaarkalender. Klik op een weeknummer of dag om die week te openen. Met "Zoek datum" (`dd-mm` of `dd-mm-jjjj`) spring je naar een dag; die dag wordt geel gemarkeerd. Rechts staan het **overzicht** (contracturen, gewerkte uren, verschil) en de **roostervrije dagen**.
- **Urenoverzicht**: alle weektotalen van het jaar per medewerker. De huidige week is groen. Klik op een getal om die week te openen. Exporteren als CSV kan ook.
- **Zoeken**: zoek op naam of initialen (minimaal 3 tekens) of op dienstcode, eventueel binnen een periode. Diensten met afwijkende tijden krijgen de markering *afwijkend*.

Het **jaartotaal** telt de ISO-weken W1 t/m W52/W53 van dat jaar, net als in Excel. Week 1 van 2026 begint dus op maandag 29-12-2025.

## 7. Beheer

| Scherm | Wat |
|---|---|
| Medewerkers | toevoegen, initialen (worden voorgesteld), contracturen per jaar, functie, e-mail, volgorde (▲▼), archiveren of verwijderen |
| Dienstcodes | nummer, omschrijving, standaardtijden, kleuren (met live voorbeeld), agenda-instellingen; voorbeeldpakket; kleurregels voor opmerkingen |
| Vakanties | naam, van en tot; het aantal werkdagen wordt berekend |
| Feestdagen | per jaar automatisch; aan of uit zetten; eigen roostervrije dagen toevoegen |
| Gebruikers | accounts, rollen, koppeling met een medewerker, wachtwoord resetten |
| Instellingen | teamnaam, toeslagen, blanco-code, logboek-bewaartermijn, alleen-lezen deellink |
| Logboek | elke wijziging met wie, wanneer, oud en nieuw; te filteren |
| Uren herberekenen | na het wijzigen van toeslagfactoren of feestdagen |

### Archiveren of verwijderen?

- **Archiveren** (aanbevolen bij vertrek): de medewerker verdwijnt uit de weken vanaf de gekozen datum. Oude diensten en uren blijven bewaard en zichtbaar in oude weken.
- **Verwijderen**: alleen zonder diensten, of na een expliciete bevestiging dat alle diensten ook verdwijnen.

### Standaardtijden van een code wijzigen

Een nieuwe standaardtijd geldt alleen voor **nieuwe invoer**. Wil je ook de toekomstige diensten aanpassen? Gebruik dan bij de code **Tijden toepassen…**. Je ziet eerst hoeveel diensten er veranderen.

### Toeslagen wijzigen

Uren worden berekend op het moment van opslaan. Heb je de factor voor zaterdag of zondag gewijzigd, gebruik dan **Uren herberekenen**. Let op: dat verandert ook historische totalen.

## 8. Het oude Excel-bestand overzetten

1. Ga naar *Beheer → Excel-import* en upload `Rooster_2026.xlsm`.
2. Je ziet een voorbeeld:
   - aantallen medewerkers, codes, vakanties en diensten;
   - diensten met afwijkende tijden;
   - de controle van alle weektotalen tegen Excel.

   Uren die in Excel met de hand zijn aangepast (bijvoorbeeld een dienst tot 13:00 met daarna een training, waarbij de uren van de hele dag zijn getypt), worden overgenomen als *zelf ingevulde uren*. Zo komen alle totalen precies overeen met Excel.
3. Vink de bevestiging aan en klik op **Definitief importeren**. Er wordt eerst automatisch een back-up gemaakt.

## 9. Back-ups

*Beheer → Back-ups*: nu een back-up maken, downloaden of terugzetten. Bij het terugzetten wordt de huidige stand eerst bewaard als veiligheidsback-up. Elke nacht maakt de app zelf ook een back-up.

## 10. Twee planners tegelijk

Heeft een andere beheerder dezelfde dag van dezelfde medewerker al opgeslagen terwijl jij er nog mee bezig bent? Dan krijg je bij die cel een melding en wordt jouw wijziging daar niet opgeslagen. Ververs de pagina om de nieuwste stand te zien. Er gaat niets stilletjes verloren.
