# Wijzigingen

## [Onuitgebracht]

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
