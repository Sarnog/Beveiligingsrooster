# Wijzigingen

## [Onuitgebracht]

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

## [1.1.1] – 2026-10-01

### Opgelost
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
