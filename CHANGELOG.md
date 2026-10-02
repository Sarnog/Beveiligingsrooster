# Wijzigingen

## [Onuitgebracht]

### Toegevoegd
- **Roosterpatronen: week kopiëren.** In het patroon kopieer je een week in één keer naar één of
  meer andere weken van de cyclus (bijvoorbeeld week 1 naar 3, 5 en 7). De doelweken worden precies
  gelijk aan de bronweek; er wordt pas opgeslagen als je op *Opslaan* klikt.
- **Beheer → Roosterpatronen → Rooster herhalen.** Plan een vast rooster van bijvoorbeeld 8 weken
  in het gewone weekrooster en herhaal het voor het hele team (of gekozen collega's) naar latere of
  eerdere weken. De cyclus loopt door vanaf de bronweken: 8 weken na bronweek 1 komt weer
  bronweek 1, ook als je midden in de cyclus begint. Zelfde werkwijze als uitrollen: droogloop,
  overschrijven of aanvullen, feestdagen invullen of overslaan, niets op of na een archiefdatum,
  vooraf een back-up (*voor-herhalen*), logboek en Google-synchronisatie alleen voor de geraakte
  collega's. Diensten zonder code tellen als vrij (met een waarschuwing in het voorbeeld). De
  periode mag de bronweken niet overlappen.

### Gewijzigd
- `services/patronen.py`: uitrollen en herhalen delen dezelfde berekening en uitvoering.

### Opgelost
- **Bestaand roosterpatroon opslaan gaf HTTP 500** (IntegrityError op `uq_patroon_week_dag`) zodra
  er een cel bleef staan. De dagen worden nu per week en dag bijgewerkt, toegevoegd of verwijderd;
  ook na *Week kopiëren*.
- **Voorbeeld en resultaat gelijk:** bij *Definitief toepassen* wordt nu ook de inhoud vergeleken
  (een vingerafdruk van de patrooncellen of van de bronweken per medewerker). Is die intussen
  gewijzigd, dan verandert er niets en verschijnt *gewijzigd sinds het voorbeeld; controleer het
  bijgewerkte voorbeeld*.
- **Rooster herhalen wist geen collega's meer zonder bronrooster:** standaard staan alleen
  medewerkers aangevinkt met minstens één dienst in de bronweken. Kies je toch iemand zonder, dan
  waarschuwt het voorbeeld dat in de doelperiode alles gewist wordt.
- **Dienstcodes in een patroon:** een code die in een roosterpatroon staat, kan niet meer
  hernummerd of verwijderd worden (de melding noemt de patronen); deactiveren kan wel.
- **Testgaten uit de mutatietests** gedicht: dienst op de laatste dag van de periode, een patroon
  van 12 weken, week 8 van 8 als bron, herhalen met feestdagen overslaan, de lengte van de
  bronperiode, `uren_uit_minuten` met begin = eind (0 uur, zoals de VBA; ongewijzigd), `dagfactor`
  zonder `is_feestdag` en de volledige foutmeldingen van de keuzes.
- **Bulkacties met optimistic locking:** de Excel-import, uitrollen en herhalen controleren de
  versie van elke bestaande dienst (zoals het weekrooster). Wijzigt een planner tegelijk een dienst,
  dan wordt alles teruggedraaid met een duidelijke melding.
- **Rooster herhalen: exact kopiëren.** Naast *Alleen codes* is er *Exact kopiëren (zoals Week
  kopiëren)*: afwijkende tijden, zelf ingevulde uren, vrije dienstnamen en opmerkingen gaan mee.
  Daarbij telt een vrije dienstnaam met tijden bij import, patronen en herhalen nu als handmatige
  tijden, net als in het rooster.
- `SESSIE_UREN` met een ongeldige waarde laat de app niet meer crashen: terug naar 12 uur, met
  een waarschuwing in het log.
- XSS-regressietest voor de weekpagina (naam, opmerking en dienstnaam, raster en telefoon),
  inhoudelijke controles in smoke-tests en een overbodige patch opgeruimd.
- Onderhoud: formulier-, sessie- en toepassen-logica van uitrollen en herhalen gedeeld in één
  helper; geen hergebruik meer van de variabele `fout` na `except ... as fout`.

## [1.6.0] – 2026-10-01

### Toegevoegd
- **Excel-export met echte formules** (gewone `.xlsx`, zonder macro's): uren per dienst
  rekenen zoals de app (pauzestaffel, toeslag zaterdag/zondag/feestdag met de hoogste factor,
  opmerkingtijden, afronding op kwartieren met bankiersafronding), het weektotaal is een `SUM`
  van dienst 1 en dienst 2, het urenoverzicht verwijst naar de weektotalen (met jaartotaal,
  contracturen en verschil), vakanties met `NETWORKDAYS`. Dienstnaam en standaardtijden zoeken
  de code uit het code-raster op in *Lijsten* (ook `4/7`). Een verborgen blad *Rekenhulp* zorgt
  dat Excel ook bij een half kwartier of precies op een pauzegrens precies zo afrondt als de app.
  Zelf ingevulde uren blijven een vaste waarde (rood, met een opmerking). Nieuwe bladen
  *Feestdagen* en *Rekenhulp*; in *Lijsten* de instellingen voor de uren.
- **Exportkeuzes**: één week (`rooster-2026-W10.xlsx`), een vrije periode (binnen één
  roosterjaar), een heel jaar of het jaarrooster van één persoon (`rooster-2026-ma.xlsx`); bij
  week, periode en jaar optioneel één medewerker. Alles op de server gecontroleerd, met een
  melding op het scherm.
- **Pauzeaftrek instelbaar** in *Beheer → Instellingen → Pauze*: aan/uit en een staffel van
  hooguit 5 regels (*meer dan X uur: Y uur eraf*, de hoogste regel telt). Standaard precies het
  oude gedrag (meer dan 5,5 uur: 0,5). Logboekregel met oud en nieuw en de tip *Alle uren
  herberekenen*. Geldt overal: rooster, herberekenen, import (controle met de regels uit het
  bestand) en de Excel-export.
- **Beheer → Statistieken**: mislukte Google-synchronisatie en de wachtrij, de laatste
  geslaagde back-ups (waarschuwing na 2 dagen) en de laatste mislukte, het aantal diensten,
  uren tegenover contracturen tot nu toe, diensten met zelf ingevulde uren of afwijkende tijden,
  mislukte inlogpogingen en blokkades (24 uur) en actieve API-tokens. Korte melding op de
  Beheer-startpagina bij syncfouten, een te oude back-up of mogelijk dubbel getelde uren.
- **Beheer → Roosterpatronen**: een cyclus van 1 t/m 12 weken (standaard 8) met per dag een
  code-cel als in het code-raster, of een sjabloon uit het rooster van één medewerker.
  Uitrollen over meer medewerkers met een eigen startpositie in de cyclus, overschrijven of
  alleen lege dagen, feestdagen invullen of overslaan, niets op of na een archiefdatum. Met
  droogloop; toepassen in één keer, met vooraf een back-up (*voor-patroon*), een logboekregel per
  gewijzigde dienst en Google-synchronisatie alleen voor de geraakte collega's.

### Gewijzigd
- **De Excel-export staat in Beheer → Excel import/export** (het scherm heet nu zo, met de
  delen *Importeren* en *Exporteren*) en is **alleen voor de beheerder**. De knoppen
  *Exporteren (Excel)*, *Excel…* en *Meer exportkeuzes…* op de weekpagina, de jaarkalender en
  het urenoverzicht, *Rooster exporteren (Excel)…* bij zoeken en de route `/export/` zijn weg.
  **Collega's hebben geen Excel-export meer**; de CSV-exports blijven.
- Import: formulecellen zonder opgeslagen waarde (een export die nog niet in Excel is geopend)
  worden goed gelezen: tijden uit een opzoekformule = de standaardtijden van de code, uren uit
  een formule zijn niet *zelf ingevuld*, een weektotaal zonder waarde geeft geen vals verschil.
- De import en roosterpatronen gebruiken dezelfde code om wijzigingen door te voeren
  (`roosteracties.py`).
- Databasemigratie `0007` (tabellen voor roosterpatronen).

### Opgelost
- **Twee diensten op één dag telden uren dubbel** als dienst 1 *zelf ingevulde uren* had,
  bijvoorbeeld na de import van het oude Excel (dienst plus een training op de opmerkingregel,
  samen getypt als dagtotaal). Werd het tweede deel een echte tweede dienst (`4/13`), dan bleef
  dienst 1 op het dagtotaal staan en kwam dienst 2 er nog eens bij. Nu vervallen de zelf
  ingevulde uren van dienst 1 als er een tweede dienst bij komt (logboek met de oude waarde),
  zodat elke dienst zijn eigen uren telt. Dagen die al zo opgeslagen waren, staan in
  *Beheer → Statistieken* onder *Mogelijk dubbel geteld*.

## [1.5.0] – 2026-10-01

### Toegevoegd
- **Rooster exporteren naar MS Excel (.xlsx)**: knop *Exporteren (Excel)* op de weekpagina, de
  jaarkalender en het urenoverzicht, en *Meer exportkeuzes…* (een jaar of een periode, eventueel
  één medewerker). Per ISO-week een blad zoals het weekrooster, in de kleuren van de dienstcodes
  en kleurregels, met de tweede dienst rechts (vanaf kolom AK); plus de bladen *Lijsten*,
  *Urenoverzicht*, *Vakanties* en *Kalender*. Het bestand kan weer geïmporteerd worden.
  Tekst die met `= + - @` begint blijft tekst (geen formule). Niet via de deellink.
- **Importeren: jaar kiezen.** Na het uploaden kies je *Rooster voor jaar* (verplicht; voorstel
  uit Kalender!E2 of de bestandsnaam, nooit stil het huidige jaar). Alleen dat jaar wordt gevuld;
  afwijkingen van E2 of van de datums in de weekbladen worden gemeld, bladen van een ander jaar
  overgeslagen. Zo kan het rooster van volgend jaar naast het huidige worden ingelezen.
- **Importeren: kiezen wat overschreven wordt.** *Alles* (alleen de weken uit het bestand),
  *gedeeltelijk* (medewerkers en/of een periode) of *alleen lege dagen aanvullen*. Per onderdeel
  (contracturen, toeslagen, vakanties, nieuwe dienstcodes) *overnemen* of *niet overnemen*;
  toeslagen standaard alleen voor het huidige jaar, bestaande dienstcodes nooit gewijzigd. De
  droogloop toont per medewerker nieuw/vervangen/verwijderd/ongewijzigd en de dagopmerkingen die
  veranderen; bevestigen kan alleen met de keuzes van het getoonde voorbeeld.

### Opgelost (audit 1.4.4)
- **Import wiste diensten in weken die niet in het bestand stonden** (H1). Nu alleen de weken
  met een blad; de droogloop toont hoeveel bestaande diensten per medewerker verdwijnen.
  Diensten met een Google-afspraak worden leeggemaakt tot de worker de afspraak heeft verwijderd.
  Na de import alleen een agenda-sync voor de geraakte medewerkers.
- **Dubbele Google-afspraken na een half mislukte sync** (H2): elke dienst krijgt een vaste
  event-ID; bestaat die al bij Google, dan wordt de afspraak bijgewerkt.
- **De worker kon een net opnieuw ingevulde dienst verwijderen** (M1): opruimen en het event-ID
  wegschrijven gebeuren alleen als de dienst sinds het lezen niet gewijzigd is.
- **Vrije dienstnaam van dienst 2 verdween via het coderaster** (`4/` → `5/`) (M2).
- **Worker stopt netjes bij `docker stop`** (SIGTERM/SIGINT na de lopende ronde); `init: true`
  in `docker-compose.yml` (M3).
- **Na het terugzetten van een back-up** worden alle gekoppelde agenda's opnieuw
  gesynchroniseerd (M4).
- **Inlogvloed:** harde grens per IP-adres (40 fouten in 15 minuten) vóór de wachtwoordcontrole,
  zonder nieuwe databaserijen; tijdens een IP-blokkade geen regel per poging in het logboek (M5).
- **Deellink toont geen contracturen en weektotalen meer** (M6).
- Kleinere punten (L1–L15, S1–S3): dezelfde controle van gebruikersnamen, initialen, codenummers
  en lengtes in setup, `flask maak-beheerder`, Beheer en import; te grote getallen in een adres
  of formulier geven geen serverfout meer (en `/api/…` antwoordt bij een fout altijd in JSON);
  nooit meer een tweede dienst zonder eerste; ongeldige archiefdatum geeft een melding;
  `sync_dag` buiten de sync-periode ruimt alleen op; begin = eind wordt geweigerd (overal duur 0);
  opmerkingtijden op de telefoonkaart ook met alleen een eindtijd; zoeken meldt het afkappen op
  5000; begrensde lijsten in `/api/cellen`; de laatste-beheerdercontrole binnen de
  schrijftransactie; de nachtelijke back-up wordt herkend aan het bestand (ook na een herstart);
  aanvullingen gaan mee bij het hernoemen van een dienstcode; herbereken-tip bij eigen
  roostervrije dagen; de tijdzone uit Beheer is binnen 5 s in elk proces actief; de xlsx-import
  is beschermd tegen zip-/XML-bommen; ICS escapet een losse `\r`; back-ups met eigen triggers of
  views worden geweigerd.

### Gewijzigd
- **Logboek per wijziging** (oud → nieuw) ook bij week kopiëren, standaardtijden toepassen, de
  import en het verwijderen van een medewerker.
- `htmx` verwijderd (werd nergens gebruikt).
- `feestdagen_in_periode()` schrijft niet meer in de database (geen verborgen commit).
- Urenoverzicht zonder een query per medewerker; extra tests die eerder ongemerkte fouten vangen.
- Bij `/3` (alleen een tweede dienst) bestaat dienst 1 voortaan als lege plaatshouder. In de API
  blijft `dagen` op die plaats `null`.

## [1.4.4] – 2026-10-01

### Toegevoegd
- **Logniveau en debuglog instellen in Beheer** (*Beheer → Debuglog*): logniveau (DEBUG, INFO,
  WARNING, ERROR) en het debuglog-bestand aan/uit, zonder `docker-compose.yml`/`.env` aan te passen
  en zonder herstart (binnen een halve minuut actief in website en worker). *Volgens .env* gebruikt
  weer `LOG_NIVEAU` en `DEBUG_LOG`. Elke wijziging komt in het logboek.
- **Back-ups verwijderen** in *Beheer → Back-ups* (met bevestiging; komt in het logboek).

### Opgelost
- **Aanvulling achter de dienstnaam:** typ je iets achter de dienstnaam (*VW Vroeg – tot 12:00*),
  dan blijven de code, de achtergrondkleur en de tijden staan. Voorheen werd het een vrije
  dienstnaam zonder kleur. (Cellen die al zo zijn opgeslagen: code opnieuw invullen.)
- **Print weekrooster:** de pagina-indeling wordt nu echt opgemeten in plaats van geschat. Met
  lange namen, functies of dagopmerkingen in de kop liep de week eerder al bij 10 medewerkers
  over naar een tweede pagina. Nu: t/m 10 medewerkers altijd één A4, 13 met overal twee diensten
  ook (kleinere letters), en daarboven hooguit 10 medewerkers per pagina (14 = 10 + 4,
  25 = 10 + 10 + 5). Elke pagina is een eigen tabel met de kopregel; dat werkt in elke browser.

### Gewijzigd
- Geen rode hoekjes en rode stippellijnen meer bij handmatig aangepaste tijden en uren (overgenomen
  uit Excel, zonder functie). De tip *Handmatig aangepast* bij de muis blijft.

## [1.4.3] – 2026-10-01

### Gewijzigd
- **Print van het weekrooster:**
  - geen lege regel *Reserve 1* meer onderaan;
  - tot en met 10 medewerkers past de week altijd op één A4, ook als iedereen elke dag twee
    diensten heeft;
  - past het niet op één pagina, dan wordt het meerdere pagina's in normale lettergrootte (niet
    piepklein); elke pagina begint met het weeknummer en de datums, en een medewerker staat
    altijd helemaal op één pagina;
  - de grijze urenkolom per dag is iets breder, zodat ook `16,00` (zondag) er helemaal in past.

## [1.4.2] – 2026-10-01

### Gewijzigd
- **Twee diensten op een dag: geen extra regels meer.** Elk medewerkerblok houdt vier regels.
  Op een dag met één dienst staat bovenaan de opmerking en onderaan de dienst (zoals altijd).
  Op een dag met twee diensten schuift dienst 1 naar de bovenste twee regels en komt dienst 2
  op de onderste twee. De opmerking van die dag staat dan achter de dienstnaam van dienst 1
  (bijv. *VW Vroeg – Later op dienst*); wijzigen kan weer zodra het één dienst is. De indeling
  wisselt per dag, direct tijdens het typen. De printversie volgt dezelfde indeling.
- **Weekrooster ruim sneller** (ongeveer een derde): de dagcellen van het rooster en de
  kaarten van de telefoonweergave worden in Python opgebouwd (`app/services/weekweergave.py`)
  in plaats van in de template. De HTML is precies gelijk gebleven. De prestatietest in CI
  (< 300 ms) zat eerder te krap aan de grens.

## [1.4.1] – 2026-10-01

### Opgelost
- Op de pagina **Beheer** stond in het browsertabblad `Beheer<p class="hulp">…`. Nu staat er
  alleen *Beheer*; het versienummer staat weer op de pagina zelf, onder de kop.

## [1.4.0] – 2026-10-01

**Bijwerken vanaf 1.3.0:** de database krijgt een nieuwe kolom (`update.sh` maakt eerst een
back-up en werkt de database bij). Bestaande diensten blijven precies zoals ze waren.
Teruggaan naar 1.3.0 kan alleen als er geen tweede diensten in het rooster staan: de
databasemigratie weigert dan met een duidelijke melding, zodat er niets ongemerkt verdwijnt.
Zet anders een back-up van vóór de update terug.

### Toegevoegd
- **Twee diensten per dag per persoon.** Typ in het code-raster twee codes in één cel:
  `4/7` (ook `4+7` of `4 7`). De cel toont `4/7` met een gesplitste kleur (links dienst 1,
  rechts dienst 2). In het rooster staan de twee diensten onder elkaar, elk met een eigen
  gekleurde dienstnaam, begin, eind en uren. Eén code zet dienst 1 en wist dienst 2; leeg
  (Delete) wist beide. Hooguit twee diensten per dag.
- Uren per dienst: pauze-aftrek en weekend-/feestdagtoeslag gelden per dienst; dag- en
  weektotaal, urenoverzicht en kalender tellen beide diensten op.
- Overlappen de tijden van de twee diensten, dan verschijnt er een waarschuwing in de
  statusregel (opslaan wordt niet tegengehouden).
- Collega's zien de tweede dienst in het weekrooster, op de telefoon, in *Mijn rooster*, in de
  ICS-feed en in Google Agenda (een eigen afspraak per dienst). Wijzigen kan alleen de planner.
- API: veld `volgnummer` (1 of 2) bij elke dienst, en `tweede_diensten` per medewerker in
  `/api/v1/week`. Het interne raster-API (`/api/cellen`) kent `volgnummer` en `versie2`.
- Nieuwe schermafbeeldingen: `week-twee-diensten-1280x800.png`, `week-print-a4.png` en
  `week-print-a4.pdf` in `docs/schermafbeeldingen/`.

### Gewijzigd
- **Printversie van het weekrooster** lijkt nu op het papieren rooster en blijft in kleur:
  A4 liggend, de hele pagina gevuld, groter lettertype. Kopregel met *Weeknummer*, per dag
  `ma 28-09-26` met de dagopmerking als donker label en rechts *Uren*. Per medewerker één blok
  met een dikke lijn ertussen; per dag de opmerking, de dienstnaam als gekleurde balk en
  begin/eind, met de uren in een smalle grijze kolom naast elke dag. Rechts de contracturen en
  (grijs) het weektotaal. Weekenden staan er altijd op. Past het, dan komt er onderaan één lege
  regel *Reserve 1*. Bij veel medewerkers krimpen eerst de regels en pas daarna de letters,
  zodat de week op één pagina blijft. De schermweergave is niet veranderd.
  De printtabel wordt in de browser opgebouwd uit het rooster (`app/static/js/print.js`),
  zodat de server de week maar één keer hoeft te maken; zonder JavaScript print de browser
  het gewone rooster.
- **Weekrooster sneller:** de extra regels voor een tweede dienst staan alleen in de pagina bij
  wie die week een tweede dienst heeft (het raster voegt ze toe als er een bij komt), en de
  feestdagen worden per pagina nog maar één keer opgehaald. De pagina is daardoor even snel
  als in 1.3.0 (de prestatietest eist < 300 ms).
- Datamodel: een dienst heeft nu een `volgnummer` (1 of 2); de unieke sleutel is
  (medewerker, datum, volgnummer). Databasemigratie `0006`.
- Logboek: wijzigingen aan de tweede dienst staan als *dienst 2: …* in het veld.
- *Week kopiëren* neemt ook tweede diensten mee.
- Back-ups van oudere versies (zonder `volgnummer`) kunnen gewoon teruggezet worden; ze worden
  daarbij bijgewerkt.

## [1.3.0] – 2026-10-01

> Versie 1.2.0 is per ongeluk als tussenstand uitgebracht; gebruik 1.3.0.

Onderhouds- en beveiligingsversie na een audit van 1.1.2: veel kleine en een paar
belangrijke reparaties. Na deze update moet iedereen één keer opnieuw inloggen.

**Bijwerken vanaf 1.1.x:**
1. Maak eerst een back-up (`update.sh` doet dat vanzelf).
2. Iedereen moet na de update één keer opnieuw inloggen.
3. Gebruik je Google Agenda? Klik daarna in *Beheer → Google Agenda* per medewerker één keer
   op *Volledig synchroniseren*.

### Nieuw
- **Op de telefoon:** elke pagina past nu op een telefoonscherm, zonder inzoomen of opzij
  schuiven. Het menu klapt in (☰), knoppen zijn groot genoeg om op te tikken en brede tabellen
  schuiven binnen de tabel (met een hint), met een vaste eerste kolom. Op de computer blijft
  alles hetzelfde.
- **Mijn rooster** is vernieuwd: bovenaan *Vandaag* en *Volgende dienst*, per dag een
  duidelijke kaart, en een grote knop *Toevoegen aan mijn agenda*.
- **Weekrooster op de telefoon:** per dag (het hele team) of per medewerker (zeven dagen),
  bladeren met knoppen of door te vegen. Een knop wisselt tussen deze weergave en het gewone
  raster; de keuze wordt onthouden.
- **De planner kan op de telefoon een dienst wijzigen:** tik op een dag, kies de dienst, pas
  eventueel tijden, opmerking of uren aan en tik op *Opslaan*. Je ziet vooraf hoeveel uren het
  worden. Een gelijktijdige wijziging door een andere planner wordt nooit overschreven.
- **Installeren als app** op het beginscherm van Android en iPhone (via HTTPS). De app bewaart
  geen roosterdata en laadt na een update altijd de nieuwe versie; zonder verbinding zie je
  *Je bent offline*.
- **API voor een app:** `/api/v1` (alleen lezen) met je eigen rooster, het weekrooster en de
  dienstcodes. Inloggen met een persoonlijk **API-token** dat je zelf maakt en intrekt
  (*naam rechtsboven → API-token*). Een token verloopt, staat alleen als hash in de database
  en werkt niet meer na een wachtwoordwijziging. Zie `docs/api.md` en `docs/app.md`.
- `flask terugzetten <back-up>`: een back-up terugzetten op de server, als de website niet werkt.
  `flask backup --label` accepteert alleen kleine letters, cijfers en `-`, zodat zo'n back-up
  later ook automatisch opgeruimd wordt.

### Opgelost
- **Back-ups:** een mislukte nachtelijke back-up (bijvoorbeeld een volle schijf) liet een leeg
  bestand achter en werd elke 5 seconden opnieuw geprobeerd. Bij de eerstvolgende geslaagde
  back-up ruimde de app dan alle échte back-ups op en bewaarde alleen de lege. Nu:
  - een back-up wordt eerst als tijdelijk bestand geschreven en gecontroleerd, pas daarna krijgt
    hij zijn echte naam; bij een fout wordt het tijdelijke bestand opgeruimd;
  - na een mislukte back-up wacht de worker 30 minuten en zet een regel in het logboek
    ("Back-up mislukt");
  - het opruimen telt alleen geldige automatische back-ups.
- **Weekrooster:** dezelfde dienstcode opnieuw invoeren (bijv. 4 → 5 → terug naar 4 en dan
  Opslaan) zette zelf aangepaste tijden stilletjes terug naar de standaardtijden, zonder
  logboekregel en zonder agenda-update. Een ongewijzigde code verandert nu niets meer.
- **Excel-import:** de import gebeurt nu in één keer. Ging er halverwege iets mis (bijvoorbeeld
  bij een verse installatie), dan kon er een half rooster achterblijven. Nu wordt alles
  teruggedraaid en zie je een duidelijke melding in plaats van een foutpagina.
  Dubbele diensten (zelfde medewerker en dag) worden al in de droogloop gemeld.
- **Excel-import:** een medewerker werd ook op alleen dezelfde initialen gekoppeld, waardoor
  diensten bij de verkeerde collega terecht konden komen. Alleen een gelijke naam koppelt nog;
  bij alleen gelijke initialen komt er een nieuwe medewerker en toont de droogloop een
  waarschuwing. De droogloop laat per medewerker zien hoe hij gekoppeld wordt.
- **Google Agenda:** een wijziging die binnenkwam terwijl de worker met dezelfde dag bezig was,
  kon verloren gaan. De worker zet een taak nu eerst op "bezig"; een nieuwe wijziging krijgt
  een eigen taak. Taken die na een crash op "bezig" blijven staan, gaan na 10 minuten terug
  in de wachtrij.
- **Google Agenda, gedeelde agenda (modus B):** een volledige synchronisatie of ontkoppelen van
  één collega verwijderde ook de afspraken van andere collega's in dezelfde agenda. Nu worden
  alleen de eigen afspraken van die medewerker aangeraakt.
- **Back-up terugzetten:** een back-up van een nieuwere versie van de app terugzetten legde de
  app plat (ook na een herstart). Nu wordt dat vooraf geweigerd met een duidelijke melding.
  Mislukt het bijwerken van een oudere back-up, dan wordt de vorige stand automatisch
  teruggezet. Een beschadigde back-up wordt geweigerd (de integriteitscontrole telt nu echt).
  Een mislukte upload wordt altijd opgeruimd.

- **Toeslagfactoren:** "inf" of "nan" werd geaccepteerd, waarna elke weekenddienst een foutpagina
  gaf. Factoren moeten nu een gewoon getal groter dan 0 en hooguit 10 zijn (instellingen en setup).
- **Tijdzone:** een onbekende tijdzone (tikfout) werd opgeslagen, waarna Google elke afspraak
  weigerde. De tijdzone wordt nu gecontroleerd. Er is nog maar één bron: de instelling
  (standaard de `TZ` uit docker-compose), voor de klok, de ICS-feed en Google Agenda.
- **Blanco-code:** mocht gelijk zijn aan een bestaande dienstcode, die daarna niet meer in te
  voeren was. Dat wordt nu geweigerd.
- **Worker:** een fout in de agenda-synchronisatie kon stil blijven of de back-up tegenhouden.
  Elke stap heeft nu een eigen foutafhandeling met een duidelijke regel in de log.
  `google-auth-httplib2` en `httplib2` staan nu ook echt in `requirements.txt`.
- **Weekrooster:** twee beheerders die exact tegelijk dezelfde dienst opslaan, kunnen elkaars
  wijziging niet meer ongemerkt overschrijven; de tweede krijgt een melding (409).
- **Excel-import:** na de import worden de gekoppelde Google-agenda's automatisch bijgewerkt.
  Lukt het plannen daarvan niet, dan blijft de import gewoon staan (met een regel in de log);
  er komt geen onterechte melding "er is niets geïmporteerd".
- De app-log zweeg na het terugzetten van een back-up (de databasemigratie zette de loggers uit).
- Kleine reparaties:
  - een agenda-taak die tijdens een fout verdwijnt, of een onverwachte fout bij Google, legt de
    wachtrij niet meer stil (de taak wordt later opnieuw geprobeerd);
  - tekens als "²" in een tijd- of codecel geven een gewone foutmelding in plaats van een
    foutpagina; ongeldige verzoeken en datums buiten 1950–2150 worden netjes geweigerd;
  - na het wijzigen van een codenummer, een vakantie of een feestdag worden de agenda-afspraken
    (met de dagtekst) bijgewerkt;
  - "Week kopiëren" plant geen diensten meer voor een medewerker na zijn archiefdatum;
  - een standaard feestdag kan niet meer dubbel ontstaan (dubbele worden bij de update
    opgeruimd);
  - een bewaartermijn van 0 dagen en 0 uur wiste het hele logboek; nu betekent dat "nooit
    opschonen";
  - zoeken op "___" of "%%%" vindt niet meer alles;
  - kleurregels zijn uniek zonder op hoofdletters te letten en hooguit 60 tekens;
  - Excel-import: een onmogelijk jaar in Kalender!E2 geeft een duidelijke melding, lange
    dienstnamen worden ingekort en overschreven toeslagen komen met hun oude waarde in het
    logboek;
  - `BASE_URL` wordt nu echt gebruikt voor de ICS-links en de deellink.
- Een handmatige back-up die mislukt (bijv. volle schijf) geeft een melding in plaats van een
  foutpagina.
- **Printen:** met 15 medewerkers kwam de week op twee pagina's; nu altijd op één A4 liggend.
  De weektotalen worden niet meer afgekapt.
- Het weekrooster laadt sneller: contracturen en dienstcodes worden in één keer opgehaald in
  plaats van per medewerker (gemeten: ongeveer 25 ms met 15 medewerkers en een vol jaar).

### Gewijzigd
- **Uitbrengen:** alleen een push naar `main` maakt nog een versie-tag, een GitHub-release en
  een image (`<versie>` en `latest`). Een zijbranch of pull request test alleen. Daardoor kan er
  niet meer per ongeluk een halve versie uitkomen, zoals bij 1.2.0. De GitHub Actions zijn
  bijgewerkt naar de nieuwste hoofdversies en vastgezet op een vaste commit.
- Wachttijden van de agenda-wachtrij en de loginblokkade rekenen in UTC; het dubbele uur bij de
  overgang naar wintertijd heeft er geen invloed meer op.
- Back-ups met een label (handmatig, voor-update, voor-import, voor-terugzetten, upload) worden
  na 90 dagen opgeruimd; de nieuwste 10 blijven altijd staan.
- Geüploade Excel-bestanden van een afgebroken import worden na een dag opgeruimd.
- Voorbeeldpakket: de kleurregels heten nu "Locatie A" en "Locatie B" (geen echte plaatsnamen).
  Bestaande kleurregels blijven ongewijzigd.
- Opgeruimd: ongebruikte code (o.a. dubbele dagnamen, oude hulpfuncties) en een ongebruikte
  cookie-instelling.
- **Debuglog:** met `LOG_NIVEAU` (DEBUG, INFO, WARNING, ERROR) stel je in hoeveel er in
  `docker compose logs` komt. Met `DEBUG_LOG=1` komen alle details van website en worker in
  `data/logs/debug.log` (maximaal 4 × 5 MB), te bekijken en te downloaden via *Beheer → Debuglog*.
  Wachtwoorden, SQL en geheime tokens komen er nooit in.
- De Docker-image wordt gebouwd met vaste pakketversies (`requirements.lock`), zodat elke
  build hetzelfde is. `requirements.txt` blijft de bron.
- CI controleert nu ook de databasemigraties op een lege database (`flask db upgrade` en
  `flask db check`) en meet de testdekking (branch-coverage); er zijn veel tests bijgekomen
  (o.a. met CSRF-bescherming aan, de commando's, de worker en de Google-koppeling).
- README aangevuld: inlogblokkade en reverse proxy, `COOKIE_SECURE`, `TZ`, `GUNICORN_*`,
  `DATABASE_URL`, bewaartermijn van back-ups en terug naar de vorige versie na een mislukte
  update.
- Databaseversies 0004 en 0005 (gaan automatisch bij de start): sessieversie per gebruiker,
  unieke standaard feestdagen per jaar, wachttijden in UTC, en een tabel voor API-tokens.
- Elke versie wordt nu vóór het uitbrengen automatisch getest: de Docker-image wordt gebouwd en
  gestart op een lege datamap (inclusief back-up en terugzetten), het bijwerken vanaf 1.1.2 wordt
  getest met voorbeelddata, en alle pagina's worden in een echte browser op telefoon-, tablet-
  en computerformaat gecontroleerd.

### Beveiliging
- **Sessies:** na het wijzigen of resetten van een wachtwoord, het deactiveren van een account of
  een rolwijziging worden alle andere sessies van die gebruiker direct uitgelogd. Na het
  terugzetten van een back-up moet iedereen opnieuw inloggen.
- **Achter een proxy:** zonder `PROXY_VERTROUWEN=1` lijkt iedereen van hetzelfde IP-adres te
  komen; na 20 foute pogingen werd dan het hele team geblokkeerd. Nu komt een collega met het
  juiste wachtwoord er nog steeds in (elke naam krijgt dan nog één poging). Komt er een
  `X-Forwarded-For`-header binnen terwijl `PROXY_VERTROUWEN` uit staat, dan staat er een
  waarschuwing in de log.
- CSV-exports: cellen die met `=`, `+`, `-` of `@` beginnen, krijgen een `'` ervoor, zodat
  Excel ze nooit als formule uitvoert.
- De geheime tokens van de ICS-feed en de deellink staan niet meer in de toegangslog.
- Verkeerde bestandsrechten in `./data` (na een commando zonder `-u rooster`) geven een
  duidelijke melding met de oplossing.
- **Inloggen:** een bezoeker zonder account kon de database onbeperkt laten groeien met extreem
  lange gebruikersnamen. De gebruikersnaam wordt nu op 64 tekens afgekapt, een blokkade komt
  maar één keer in het logboek, alle logboekvelden zijn begrensd en loginpogingen ouder dan een
  dag worden dagelijks opgeruimd.
- Inloggen met een onbekende gebruikersnaam of een gedeactiveerd account duurt even lang als met
  een bestaande (je kunt aan de responstijd niet meer zien welke namen bestaan).
- Via HTTPS (Secure-cookies aan) stuurt de app nu `Strict-Transport-Security` mee; zonder HTTPS
  niet, zodat je jezelf op een LAN-adres niet buitensluit. De Content-Security-Policy blokkeert
  nu ook plug-ins (`object-src 'none'`).

## [1.1.2] – 2026-10-01

### Opgelost
- Wijzigingen in het weekrooster werden nog steeds direct opgeslagen. Oorzaken:
  - de beveiliging aan serverkant (alleen opslaan via de knop) zat niet in een gebouwde image,
    omdat een andere wijziging al als 1.1.1 was uitgebracht;
  - er werd een oud script geladen (cache in de browser of een reverse proxy).
- De server slaat alleen nog op bij een expliciete opdracht van de knop **Opslaan**; anders wordt
  alleen een voorbeeld berekend. Een oud script kan dus niets meer opslaan.
- Scripts en CSS hebben het versienummer in het adres; pagina's en API-antwoorden krijgen
  `Cache-Control: no-store`, zodat ook een proxy geen oude versie meer doorgeeft.
- Het script controleert of het bij de pagina hoort; zo niet, dan kan er niets gewijzigd worden en
  verschijnt de melding om de pagina te verversen.
- Er is nog maar één knop **Opslaan** (bovenaan bij de weeknavigatie).
- Opslaan direct na het typen (bijv. met Ctrl+S) kon een onterechte foutmelding geven, omdat het
  voorbeeld en het opslaan tegelijk bij de server aankwamen. Alle verzoeken gaan nu na elkaar.
- CI: een push met gewijzigde code onder een al bestaand versienummer faalt nu met een duidelijke melding.

## [1.1.1] – 2026-10-01

### Opgelost
- Na de update naar 1.1.0 kon de browser nog het oude script uit zijn cache gebruiken, dat elke
  wijziging direct opsloeg (en geen waarschuwing gaf bij het verlaten van de pagina).
  - Scripts en stylesheet hebben nu het versienummer in de URL, zodat de browser na elke
    update het nieuwe bestand ophaalt.
  - De server slaat alleen nog op bij een expliciete opdracht van de knop **Opslaan**; zonder die
    opdracht wordt alleen een voorbeeld berekend. Een oud script kan dus nooit meer iets opslaan.
  - De oude route die dagopmerkingen direct opsloeg, is verwijderd.
- Google Agenda, modus A: de knop was uitgeschakeld (klikken deed niets) als de medewerker geen
  e-mailadres had, bijvoorbeeld na een Excel-import. Het e-mailadres kan nu direct bij de knop
  ingevuld worden en wordt bij de medewerker bewaard; zonder e-mailadres volgt een duidelijke melding.
- Duidelijke meldingen als Google de sleutel weigert of de Calendar API uit staat
  (voorheen: "Verbindingsfout").
- Maximaal 30 seconden wachten op Google, zodat een pagina nooit blijft hangen.
- Koppelknoppen tonen "Bezig…" en werken maar één keer per klik (geen dubbele agenda's).
- Mislukt het delen van een nieuwe agenda, dan wordt die agenda weer opgeruimd.

## [1.1.0] – 2026-10-01

### Gewijzigd
- Weekrooster: wijzigingen worden niet meer automatisch opgeslagen. Je ziet direct het resultaat
  (dienstnaam, tijden, uren; berekend door de server als voorbeeld), maar pas bij **Opslaan**
  (of Ctrl+S) wordt alles in één keer bewaard. Gewijzigde cellen zijn oranje gemarkeerd en de knop
  toont het aantal wijzigingen.
- Wie de pagina wil verlaten met niet-opgeslagen wijzigingen (menu, andere week, weekkiezer,
  uitloggen, formulieren) krijgt een vraag met **Opslaan**, **Terug** of **Doorgaan** (wijzigingen
  vergeten). Bij sluiten of verversen van de browser toont de browser zijn eigen waarschuwing.
- Ctrl+Z maakt niet-opgeslagen wijzigingen ongedaan.

### Opgelost
- Een voorbeeldberekening kon ongemerkt gegevens opslaan als voor dat jaar nog feestdagen
  aangemaakt moesten worden.

## [1.0.1] – 2026-09-30

### Opgelost
- Excel-import: uren die in Excel met de hand waren aangepast (bijvoorbeeld een dienst tot 13:00
  met daarna een training 13:00–17:00, met de uren van de hele dag in de urenkolom) werden opnieuw
  uit de tijden berekend. Daardoor kwamen de gewerkte uren van enkele medewerkers 3,5 tot 4 uur
  lager uit dan in Excel. Deze uren worden nu overgenomen als *zelf ingevulde uren*; alle totalen
  komen overeen met het Excel-overzicht.
- Het importvoorbeeld toont deze diensten apart.

## [1.0.0] – 2026-09-30

Eerste volledige versie: vervangt het Excel-rooster met macro's.

### Fase 4 – afronding
- Excel-import (.xlsm) met droogloop, controle van de weektotalen (kolom Z) en automatische back-up vooraf.
- Zelf ingevulde uren en vrije dienstnamen (zoals in Excel bij bijvoorbeeld een cursus zonder tijden);
  migratie 0003.
- Back-ups maken, downloaden en terugzetten in de webinterface (met veiligheidsback-up en migraties).

### Fase 3 – agenda
- Google Agenda-koppeling via een service-account: modus A (app maakt en deelt een agenda) en
  modus B (gedeelde bestaande agenda); test, volledige synchronisatie en ontkoppelen.
- Asynchrone sync-wachtrij met samenvoegen (debounce), exponentiële backoff en foutstatus;
  alleen eigen afspraken (gemarkeerd) worden aangeraakt, verweesde afspraken worden opgeruimd.
- Her-synchronisatie na wijziging van dienstcode, medewerkersnaam, dagopmerking of voorvoegsel.
- Geheime ICS-feed per medewerker (vernieuwen/intrekken), tijden in UTC (zomer-/wintertijd correct).
- Handleiding docs/google-agenda.md.

### Fase 2 – het rooster
- Weekrooster met code-raster en visueel rooster naast elkaar; Excel-achtige toetsenbordbediening
  (pijltjes, Tab, Enter, typen, F2, Delete, Esc, selecteren, kopiëren/plakken ook uit Excel, Ctrl+Z).
- Autosave per cel met optimistic locking; handmatige tijden gemarkeerd; dagopmerkingen automatisch
  uit feestdagen en vakanties; week kopiëren.
- Jaarkalender met kleuren, weekkiezer, datum zoeken, overzicht en roostervrije dagen.
- Urenoverzicht (W1–W53) met CSV-export, zoeken met CSV-export, logboek met filters.
- Printen: A4 liggend op één pagina met kleuren. 'Mijn rooster' en een alleen-lezen deellink.
- Handleidingen voor planner en collega's.

### Fase 1 – fundament
- Projectopzet: Flask, SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, CSRF, argon2.
- Datamodel voor alle onderdelen (medewerkers, contracturen per jaar, dienstcodes, diensten,
  dagopmerkingen, vakanties, feestdagen, instellingen, logboek, sync-wachtrij, loginpogingen).
- Setup-wizard met eenmalige setup-code.
- Rollen beheerder/gebruiker, server-side afgedwongen (403 op elke schrijvende route).
- Beheer van medewerkers, dienstcodes (+ voorbeeldpakket, kleurregels), vakanties, feestdagen,
  gebruikers en instellingen; alle wijzigingen in het logboek.
- Urenberekening exact volgens de oude Excel-VBA; kalenderlogica (ISO-weken, week 53, Pasen,
  Koningsdag op zaterdag als 27 april een zondag is).
- Draait in Docker (web + worker), `install.sh` voor Alpine en Debian, `update.sh`, `uninstall.sh`,
  Proxmox-script, CI met ruff/pytest en automatische image op ghcr.io.
