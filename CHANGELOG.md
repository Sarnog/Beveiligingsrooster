# Wijzigingen

## [Onuitgebracht]

## [1.2.0] – 2026-10-01

Onderhouds- en beveiligingsversie na een audit van 1.1.2: veel kleine en een paar
belangrijke reparaties. Na deze update moet iedereen één keer opnieuw inloggen.

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
- De app-log zweeg na het terugzetten van een back-up (de databasemigratie zette de loggers uit).

### Gewijzigd
- Wachttijden van de agenda-wachtrij en de loginblokkade rekenen in UTC; het dubbele uur bij de
  overgang naar wintertijd heeft er geen invloed meer op.
- Databaseversie 0004 (gaat automatisch bij de start): sessieversie per gebruiker, unieke
  standaard feestdagen per jaar, wachttijden in UTC.

### Beveiliging
- **Sessies:** na het wijzigen of resetten van een wachtwoord, het deactiveren van een account of
  een rolwijziging worden alle andere sessies van die gebruiker direct uitgelogd. Na het
  terugzetten van een back-up moet iedereen opnieuw inloggen.
- **Achter een proxy:** zonder `PROXY_VERTROUWEN=1` lijkt iedereen van hetzelfde IP-adres te
  komen; na 20 foute pogingen werd dan het hele team geblokkeerd. Nu komt een collega met het
  juiste wachtwoord er nog steeds in (elke naam krijgt dan nog één poging). Komt er een
  `X-Forwarded-For`-header binnen terwijl `PROXY_VERTROUWEN` uit staat, dan staat er een
  waarschuwing in de log.
- **Inloggen:** een bezoeker zonder account kon de database onbeperkt laten groeien met extreem
  lange gebruikersnamen. De gebruikersnaam wordt nu op 64 tekens afgekapt, een blokkade komt
  maar één keer in het logboek, alle logboekvelden zijn begrensd en loginpogingen ouder dan een
  dag worden dagelijks opgeruimd.
- Inloggen met een onbekende gebruikersnaam duurt even lang als met een bestaande (je kunt aan
  de responstijd niet meer zien welke namen bestaan).

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
