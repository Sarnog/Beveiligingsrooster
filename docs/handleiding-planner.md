# Handleiding voor de planner (beheerder, versie 1.4.4)

Deze handleiding is voor wie het rooster invult. Als beheerder mag je alles; collega's met de rol *gebruiker* kunnen alleen kijken, printen en exporteren.

![Weekrooster met code-raster](schermafbeeldingen/week-planner-1280x800.png)

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
| twee codes, bijvoorbeeld `4/7` (ook `4+7` of `4 7`) | **twee diensten** op die dag, zie hieronder |

### Twee diensten op één dag

![Weekrooster met twee diensten op één dag](schermafbeeldingen/week-twee-diensten-1280x800.png)

Werkt iemand op één dag twee diensten (bijvoorbeeld 's ochtends BHV en 's avonds VW Avond)?
Typ dan **twee codes** in dezelfde cel van het code-raster, gescheiden door `/`, `+` of een spatie:
`17/3`, `17+3` of `17 3`. Er kunnen er hooguit **twee** per dag.

- De cel toont `17/3` met een **gesplitste kleur**: links de kleur van dienst 1, rechts die van dienst 2.
- Er komen **geen extra regels** bij. Op die dag schuift **dienst 1 naar de bovenste twee
  regels** van het blok (dienstnaam, daaronder begin, eind en uren) en staat **dienst 2 op de
  onderste twee**. De andere dagen van die week blijven zoals ze waren.
- Elke dienst heeft **eigen tijden en uren**; je kunt ze los aanpassen in het rooster, net als
  bij één dienst. Pauze-aftrek en weekend-/feestdagtoeslag gelden per dienst. Het dag- en
  weektotaal tellen beide diensten op.
- De **opmerking** hoort bij de dag, niet bij een dienst. Op een dag met twee diensten staat
  ze achter de dienstnaam van dienst 1, bijvoorbeeld *VW Vroeg – Later op dienst*. Wijzigen
  kan pas weer als het één dienst is (bijvoorbeeld tijdelijk alleen `4` typen).
- Overlappen de tijden van de twee diensten? Dan zie je boven het code-raster een **oranje
  waarschuwing**. Opslaan kan gewoon; controleer even of het klopt.
- In het logboek staat bij wijzigingen aan de tweede dienst **"dienst 2:"** voor het veld.

**Tweede dienst weer weghalen:**

| Wat je typt in het code-raster | Gevolg |
|---|---|
| één code, bijvoorbeeld `17` | dienst 1 wordt `17`, dienst 2 verdwijnt |
| niets (**Delete**) | beide diensten verdwijnen |
| `/3` | alleen een tweede dienst (dienst 1 leeg) |

Op de telefoon zie je de tweede dienst op de dagkaart. Het bewerkpaneel op de telefoon wijzigt
alleen dienst 1; kies je daar een andere dienst, dan verdwijnt dienst 2. Twee diensten invullen
of aanpassen doe je in het code-raster op de computer.

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
- Een handmatige tijd herken je aan de tip *Handmatig aangepast* als je er met de muis op staat. Hij blijft staan tot je de **dienstcode opnieuw wijzigt**; dan komen de standaardtijden van de nieuwe code terug.

### Vrije dienst en eigen uren

Niet elke dienst heeft een code. Bijvoorbeeld een cursus of een extra ronde.

- Typ in het rooster op de **dienstnaamregel** (regel c) een eigen naam. Een eventuele code vervalt dan.
- Wil je alleen iets **achter de dienstnaam** zetten (bijvoorbeeld *VW Vroeg – tot 12:00*)? Laat de dienstnaam dan vooraan staan en typ je aanvulling erachter (na een spatie of leesteken). De code, de kleur en de tijden blijven dan gewoon staan. Haal je de aanvulling weg, dan staat er weer alleen de dienstnaam. Een nieuwe code kiezen haalt de aanvulling ook weg.
- Typ in de **urencel** (rechts van de eindtijd) zelf het aantal uren, bijvoorbeeld `8` of `7,5`. Zelf ingevulde uren:
  - gaan voor de berekening;
  - krijgen geen weekendtoeslag;
  - hebben dezelfde rode markering.
- **Delete** op de urencel zet de uren weer op automatisch.
- Een nieuwe dienstcode invoeren maakt de uren ook weer automatisch.

## 3. Opmerkingen

Elk medewerkerblok heeft vier regels per dag (bij twee diensten op een dag is de indeling anders, zie 1):

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

## 3a. Op de telefoon een dienst wijzigen

Op een telefoon (of als je **Telefoonweergave** kiest) zie je het weekrooster als kaarten: **Per dag** (één dag, het hele team) of **Per medewerker** (zeven dagen). Blader met ◀ ▶ of door te vegen.

1. Tik op de kaart van een medewerker op een dag. Er schuift een paneel omhoog.
2. Kies de **dienst** uit de lijst (met omschrijving en standaardtijden). De begin- en eindtijd worden ingevuld en je ziet direct de **uren**.
3. Pas zo nodig de **begin- en eindtijd**, de **opmerking** (met tijden) of de **eigen uren** aan. Eigen tijden worden, net als in het raster, gemarkeerd als *handmatig aangepast*.
4. Tik op **Opslaan**. Het paneel sluit en de kaart toont de nieuwe dienst.

Het opslaan werkt precies zoals in het raster: heeft een andere planner dezelfde dag intussen gewijzigd, dan krijg je een melding en wordt er niets overschreven (zie 10). Ga je weg met niet-opgeslagen wijzigingen, dan krijg je eerst de vraag *Opslaan / Terug / Doorgaan*.

Het Excel-achtige raster met toetsenbord blijft op de computer precies hetzelfde. Op een tablet kun je met **Rasterweergave** / **Telefoonweergave** wisselen; je keuze wordt per gebruiker onthouden.

![Dienst wijzigen op de telefoon](schermafbeeldingen/week-planner-dienst-wijzigen-390x844.png)

## 4. Week kopiëren

Klik op **Week kopiëren naar…**, kies de doelweek en of je de hele week of één medewerker wilt kopiëren. De doelweek wordt **gelijk gemaakt** aan deze week: daar bestaande diensten worden overschreven. Tweede diensten gaan mee.

## 5. Printen

Klik op **Printen**. De week komt liggend op één A4 (ook met 15 medewerkers, en ook als je vanaf een telefoon print), zonder het code-raster en met kleuren. Kies in het printvenster eventueel "Achtergrondafbeeldingen afdrukken" als de kleuren ontbreken.

De print ziet eruit als het vertrouwde papieren rooster:

- bovenaan *Weeknummer*, per dag de datum (`ma 28-09-26`) met eventueel de dagopmerking als donker label, en rechts de kolom *Uren*;
- per medewerker één blok met een dikke lijn ertussen: bovenin de opmerking, daaronder de dienstnaam als gekleurde balk en dan begin en eind; op een dag met twee diensten staat dienst 1 bovenin en dienst 2 eronder (net als op het scherm);
- de uren per dag in de smalle grijze kolom naast elke dag;
- rechts de contracturen en, grijs, het weektotaal;
- zaterdag en zondag staan er altijd op, ook als ze leeg zijn.

**Hoeveel past er op één A4?** De app meet de print echt op (ook lange namen, functies en dagopmerkingen tellen mee), dus er komt nooit één losse medewerker op een extra pagina terecht. Tot en met **10 medewerkers** past de week altijd op één pagina, ook als iedereen elke dag twee diensten heeft. Bij meer medewerkers worden eerst de regels lager en daarna de letters iets kleiner, zodat het zo lang mogelijk op één pagina blijft (bijvoorbeeld 13 medewerkers met overal twee diensten). Past het dan nog niet, dan wordt het **meer pagina's** met **hooguit 10 medewerkers per pagina** (14 = 10 + 4, 25 = 10 + 10 + 5):

- elke pagina begint weer met *Weeknummer* en de datums van de week;
- een medewerker staat altijd helemaal op één pagina (nooit dienst 1 op de ene en dienst 2 op de volgende pagina).

![Printversie van het weekrooster](schermafbeeldingen/week-print-a4.png)

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

*Beheer → Back-ups*: nu een back-up maken, downloaden, terugzetten of **verwijderen** (met bevestiging; komt in het logboek). Bij het terugzetten wordt de huidige stand eerst bewaard als veiligheidsback-up. Elke nacht maakt de app zelf ook een back-up. Na het terugzetten moet iedereen opnieuw inloggen, en werken bestaande API-tokens niet meer.

Werkt de website niet meer, maar draait de container nog? Dan kan het ook op de server: `docker compose exec -u rooster web flask terugzetten <naam-van-de-back-up>`.

## 10. Twee planners tegelijk

Heeft een andere beheerder dezelfde dag van dezelfde medewerker al opgeslagen terwijl jij er nog mee bezig bent? Dan krijg je bij die cel een melding en wordt jouw wijziging daar niet opgeslagen. Ververs de pagina om de nieuwste stand te zien. Er gaat niets stilletjes verloren.

## 11. Telefoon, app en API

- De hele site werkt op de telefoon; via **https://** kun je hem als app op het beginscherm zetten (Android: *App installeren*, iPhone: *Zet op beginscherm*). Zie de [handleiding voor collega's](handleiding-collega.md#als-app-op-je-beginscherm).
- Elke gebruiker kan zelf **API-tokens** maken voor een app (*naam rechtsboven → API-token*). Een token kan alleen lezen, met dezelfde rechten als het account. Het aanmaken en intrekken staat in het logboek. Een wachtwoordreset, deactiveren of een back-up terugzetten maakt de tokens van die gebruiker (of van iedereen) ongeldig. Zie [api.md](api.md) en [app.md](app.md).
