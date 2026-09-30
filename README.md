# Beveiligingsrooster

Een eigen webapplicatie voor het jaarrooster en de urenregistratie van een beveiligingsteam (ongeveer 10–15 collega's). Hij vervangt het oude Excel-bestand met macro's (`Rooster_2026.xlsm`) en draait **self-hosted in Docker**, bijvoorbeeld in een LXC-container op Proxmox met Alpine of Debian.

> **Privacy:** deze repository bevat geen namen, roosters of wachtwoorden. Alle roosterdata staat alleen op je eigen server, in de map `data/`.

<!-- Screenshot: kalender (placeholder) -->
<!-- Screenshot: weekrooster met code-raster (placeholder) -->

---

## Inhoud

1. [Wat doet de app?](#wat-doet-de-app)
2. [Hoe werkt het?](#hoe-werkt-het)
3. [Installeren](#installeren)
4. [Het docker-compose-bestand (om te kopiëren)](#het-docker-compose-bestand-om-te-kopiëren)
5. [Eerste setup](#eerste-setup)
6. [Dagelijks gebruik en beheer-commando's](#dagelijks-gebruik-en-beheer-commandos)
7. [Bijwerken](#bijwerken)
8. [Back-ups en terugzetten](#back-ups-en-terugzetten)
9. [Bereikbaarheid en HTTPS](#bereikbaarheid-en-https)
10. [Veelgestelde problemen](#veelgestelde-problemen)
11. [Ontwikkelen](#ontwikkelen)

---

## Wat doet de app?

| Onderdeel | Wat je ermee doet | Status |
|---|---|---|
| **Inloggen en rollen** | Beheerder (planner) mag alles; gebruiker (collega) mag alleen kijken, printen en exporteren | ✅ |
| **Setup-wizard** | Eerste beheerder, instellingen, dienstcodes en medewerkers invoeren | ✅ |
| **Beheer** | Medewerkers (met contracturen per jaar), dienstcodes met kleuren, vakanties, feestdagen, accounts en instellingen | ✅ |
| **Urenberekening** | Precies zoals de oude Excel-VBA: pauze-aftrek, toeslag voor zaterdag en zondag, afronding op kwartieren | ✅ |
| **Weekrooster** | Het code-raster zoals in Excel: typ een dienstcode, dan verschijnen tijden en uren vanzelf | ✅ |
| **Kalender, urenoverzicht, zoeken, logboek, printen** | De overzichten uit het Excel-bestand | ✅ |
| **Google Agenda en ICS-feed** | Diensten verschijnen automatisch in de agenda van de collega | ✅ |
| **Excel-import en back-ups in de webinterface** | Het oude `.xlsm` inlezen (met droogloop en controle van de weektotalen); back-ups downloaden en terugzetten | ✅ |

## Hoe werkt het?

```
                 ┌──────────────────── Docker-host (LXC: Alpine of Debian) ─────────────────────┐
 browser ──────► │  container "web"     Flask-app + Gunicorn op poort 8000                     │
 (LAN/proxy)     │        │              - toont de pagina's, controleert rechten               │
                 │        ▼              - rekent de uren uit bij het opslaan                   │
                 │   ./data/rooster.db  (SQLite-database, back-ups, geheime sleutel)            │
                 │        ▲                                                                     │
                 │  container "worker"  achtergrondtaken: agenda-synchronisatie, logboek        │
                 │                      opschonen (dagelijks), back-up (elke nacht na 02:00)    │
                 └──────────────────────────────────────────────────────────────────────────────┘
```

- **Twee containers, één image.** `web` bedient de website. `worker` doet de achtergrondtaken. Beide gebruiken dezelfde map `./data`.
- **Alles staat in `./data`**, naast `docker-compose.yml`:
  - `rooster.db` is de database;
  - `backups/` bevat de nachtelijke back-ups;
  - `secret_key` wordt automatisch aangemaakt;
  - later komt hier ook het Google-sleutelbestand.

  Een back-up van deze map (of van de hele LXC met Proxmox) is dus genoeg.
- **Bij elke start** werkt de `web`-container de database automatisch bij (migraties). Daarna start de webserver.
- **Rechten worden op de server gecontroleerd.** Een gewone gebruiker krijgt bij elke wijzigpoging een foutmelding (HTTP 403), ook als hij de knoppen omzeilt. Dit staat vast in de tests.
- **Geen wachtwoorden in platte tekst.** Wachtwoorden worden versleuteld opgeslagen (argon2). Na 5 foute pogingen in 15 minuten wordt inloggen tijdelijk geblokkeerd.
- **Urenberekening** (per dag, alleen over begin- en eindtijd):
  1. Eindtijd vóór de begintijd? Dan loopt de dienst door na middernacht.
  2. Meer dan 5,5 uur? Dan gaat er 0,5 uur pauze af.
  3. Daarna × de toeslagfactor: zaterdag 1,5 en zondag 2,0 (instelbaar).
  4. Tot slot afronden op kwartieren, op precies dezelfde manier als Excel. Gecontroleerd op 1899 diensten uit het oude bestand.

## Installeren

Je hebt een Linux-machine met Docker nodig. De aanbevolen opzet is een **LXC-container op Proxmox**. Daarvoor zijn er drie manieren, van makkelijk naar handmatig.

### Manier 1: alles automatisch vanaf de Proxmox-host

Log in op de Proxmox-host (shell) en voer uit:

```sh
wget -qO- https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/scripts/proxmox-maak-lxc.sh | sh
```

Dit maakt een LXC met Alpine (of `OS=debian`), zet Docker erin, start de app en toont de setup-code. Details en opties staan in [docs/proxmox-lxc.md](docs/proxmox-lxc.md).

### Manier 2: in een bestaande LXC of server (Alpine of Debian)

Als root in de container:

```sh
wget -qO- https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/install.sh | sh
```

Het script installeert Docker en maakt `/opt/beveiligingsrooster` aan met `docker-compose.yml` en `.env`. Daarna start het de app en toont het de URL en de setup-code.

> Draai je een LXC op Proxmox? Zet dan bij de container **Options → Features → Nesting** (en **keyctl**) aan, anders start Docker niet.

### Manier 3: met de hand (je hebt al Docker)

Maak een map aan, bijvoorbeeld `/opt/beveiligingsrooster`. Zet daarin het bestand hieronder als `docker-compose.yml` en start:

```sh
mkdir -p /opt/beveiligingsrooster && cd /opt/beveiligingsrooster
nano docker-compose.yml        # plak de inhoud van hieronder
docker compose up -d
docker compose logs web | grep -i setup-code
```

Open daarna `http://<ip-van-de-server>:8000/setup`.

## Het docker-compose-bestand (om te kopiëren)

Dit is precies hetzelfde bestand als [`docker-compose.yml`](docker-compose.yml) in de repository. Je hoeft niets aan te passen: zonder instellingen werkt het meteen, en de geheime sleutel wordt vanzelf aangemaakt.

```yaml
services:
  web:
    image: ghcr.io/sarnog/beveiligingsrooster:latest
    container_name: beveiligingsrooster
    command: web
    restart: unless-stopped
    ports:
      # 0.0.0.0 = bereikbaar in het LAN; 127.0.0.1 = alleen via een reverse proxy op deze host
      - "${LUISTER_ADRES:-0.0.0.0}:${POORT:-8000}:8000"
    environment:
      TZ: Europe/Amsterdam
      BASE_URL: ${BASE_URL:-}                   # bijv. https://rooster.voorbeeld.nl
      PROXY_VERTROUWEN: ${PROXY_VERTROUWEN:-0}  # 1 als er een reverse proxy/tunnel voor staat
      SECRET_KEY: ${SECRET_KEY:-}               # leeg = automatisch aangemaakt in ./data
      SESSIE_UREN: ${SESSIE_UREN:-12}
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  worker:
    image: ghcr.io/sarnog/beveiligingsrooster:latest
    container_name: beveiligingsrooster-worker
    command: worker
    restart: unless-stopped
    environment:
      TZ: Europe/Amsterdam
      BASE_URL: ${BASE_URL:-}
      SECRET_KEY: ${SECRET_KEY:-}
    volumes:
      - ./data:/data
    depends_on:
      web:
        condition: service_healthy   # eerst moet de database bijgewerkt zijn
```

**Instellingen aanpassen.** Zet een bestand `.env` naast `docker-compose.yml` (voorbeeld: [`.env.voorbeeld`](.env.voorbeeld)):

| Variabele | Standaard | Betekenis |
|---|---|---|
| `LUISTER_ADRES` | `0.0.0.0` | `127.0.0.1` als alleen een reverse proxy op dezelfde host erbij mag |
| `POORT` | `8000` | Poort op de host |
| `BASE_URL` | leeg | Openbaar adres, bijvoorbeeld `https://rooster.voorbeeld.nl`. Zet bij HTTPS ook de `Secure`-cookies aan |
| `PROXY_VERTROUWEN` | `0` | `1` achter Caddy, Cloudflare Tunnel of Tailscale |
| `SESSIE_UREN` | `12` | Hoe lang je ingelogd blijft |
| `SECRET_KEY` | leeg | Leeg laten; wordt dan bewaard in `data/secret_key` |

**Zelf de image bouwen** (in plaats van downloaden), vanuit een kopie van de repository:

```sh
docker compose -f docker-compose.yml -f docker-compose.bouwen.yml up -d --build
```

> **Voor de eigenaar van de repository:** GitHub Actions publiceert de image bij elke push naar `main` op `ghcr.io/sarnog/beveiligingsrooster`. Een nieuw pakket is op GitHub eerst **privé**. Zet het één keer op openbaar: *GitHub → je profiel → Packages → beveiligingsrooster → Package settings → Change visibility → Public*. Lukt het downloaden niet, dan bouwt `install.sh` de image automatisch zelf.

## Eerste setup

1. Open `http://<ip>:8000/setup`.
2. Vul de **setup-code** in. Die staat in de uitvoer van `install.sh`, of vraag hem op met:
   ```sh
   docker compose exec -u rooster web flask setup-code
   ```
   Door deze code kan een willekeurige bezoeker de installatie niet overnemen.
3. Doorloop de wizard:
   1. beheerdersaccount;
   2. algemene instellingen (teamnaam, toeslagfactoren, bewaartermijn logboek);
   3. dienstcodes: leeg beginnen of het **voorbeeldpakket** laden;
   4. medewerkers (mag ook later);
   5. afronden.

Daarna is `/setup` niet meer bereikbaar en is de code ongeldig.

**Accounts voor collega's** maak je aan via *Beheer → Gebruikers*. Er is geen openbare registratie. Bij de eerste login kiest de collega zelf een nieuw wachtwoord. Koppel het account aan een medewerker, dan ziet die collega direct zijn of haar eigen rooster.

## Het oude Excel-rooster overzetten

*Beheer → Excel-import* leest het oude `Rooster_2026.xlsm` in. Dat zijn:
- medewerkers en contracturen;
- dienstcodes en toeslagen;
- vakanties;
- alle weken met diensten, tijden, opmerkingen en dagopmerkingen.

Je krijgt eerst een **droogloop** met een voorbeeld en een controle van alle weektotalen tegen kolom Z in Excel. Pas na bevestiging wordt er iets opgeslagen, en de app maakt daarvóór automatisch een back-up.

Wachtwoorden en rechten uit het Excel-bestand worden **niet** overgenomen. Het geüploade bestand wordt na afloop direct verwijderd.

## Dagelijks gebruik en beheer-commando's

Voer deze commando's uit in de map met `docker-compose.yml`:

| Wat | Commando |
|---|---|
| Status | `docker compose ps` |
| Logs bekijken | `docker compose logs -f` |
| Stoppen / starten | `docker compose stop` / `docker compose start` |
| Setup-code tonen | `docker compose exec -u rooster web flask setup-code` |
| **Wachtwoord vergeten** | `docker compose exec -u rooster web flask reset-wachtwoord <gebruikersnaam>` |
| **Buitengesloten: nieuwe beheerder** | `docker compose exec -u rooster web flask maak-beheerder` |
| Nu een back-up maken | `docker compose exec -u rooster web flask backup` |
| Alle uren herberekenen | `docker compose exec -u rooster web flask herbereken-uren` |

Gebruik altijd `-u rooster`. Dan zijn nieuwe bestanden in `./data` van de app-gebruiker en niet van root.

## Bijwerken

```sh
cd /opt/beveiligingsrooster && ./update.sh
```

`update.sh` doet het volgende:
1. het maakt eerst een back-up (`data/backups/rooster-…-voor-update.db`);
2. het haalt de nieuwe image op;
3. het herstart de containers.

De database wordt bij het starten automatisch bijgewerkt. `./data` en `.env` blijven altijd ongemoeid.

Zonder script kan het ook met de hand: `docker compose pull && docker compose up -d`.

## Back-ups en terugzetten

- **Automatisch:** de worker maakt elke nacht na 02:00 een back-up in `data/backups/`. Het aantal dat bewaard blijft stel je in bij Instellingen (standaard 30).
- **Handmatig:** `docker compose exec -u rooster web flask backup`.
- **Downloaden en terugzetten in de webinterface:** *Beheer → Back-ups*. Voor het terugzetten maakt de app eerst zelf een veiligheidsback-up (`…-voor-terugzetten.db`).
- **Terugzetten via de command line** (als de webinterface niet meer werkt):
  ```sh
  docker compose down
  cp data/backups/rooster-JJJJMMDD-HHMMSS.db data/rooster.db
  rm -f data/rooster.db-wal data/rooster.db-shm
  docker compose up -d
  ```
- **Extra zekerheid:** laat Proxmox de hele LXC back-uppen (*Datacenter → Backup*, vzdump). Daar zit alles in: Docker, de app en `./data`.

## Bereikbaarheid en HTTPS

Er zijn drie mogelijkheden:

- **(a) Alleen in het LAN.** Dit is de standaard: `http://<ip>:8000`.
- **(b) Reverse proxy met Caddy.** Caddy regelt automatisch HTTPS.
- **(c) Tunnel.** Via Cloudflare Tunnel of Tailscale bereik je de app van buitenaf, zonder poorten open te zetten.

Voor (b) en (c) zet je `BASE_URL=https://…` en `PROXY_VERTROUWEN=1` in `.env`. De uitleg en een voorbeeld-`Caddyfile` staan in [docs/proxmox-lxc.md](docs/proxmox-lxc.md#https-en-bereikbaarheid).

De koppeling met Google Agenda heeft alleen **uitgaand** internet nodig. Voor de ICS-feed moet de app bereikbaar zijn voor Google, dus dan heb je (b) of (c) nodig.

## Veelgestelde problemen

| Probleem | Oplossing |
|---|---|
| Docker start niet in de LXC | Zet op Proxmox **Nesting** en **keyctl** aan (*Container → Options → Features*) en herstart de LXC. |
| `docker compose pull` geeft "denied" of "unauthorized" | Het GitHub-pakket is nog privé. Zet het op openbaar (zie hierboven), of bouw zelf: `BOUW_LOKAAL=1 sh install.sh`. |
| Setup-code kwijt | `docker compose exec -u rooster web flask setup-code` |
| Wachtwoord kwijt | `docker compose exec -u rooster web flask reset-wachtwoord <naam>` |
| Pagina niet bereikbaar | `docker compose ps`: staat `web` op *healthy*? Bekijk `docker compose logs web`. Controleer `LUISTER_ADRES` en `POORT`. |
| Na inloggen meteen weer uitgelogd (achter HTTPS-proxy) | Zet `BASE_URL=https://…` en `PROXY_VERTROUWEN=1` in `.env`, en daarna `docker compose up -d`. |
| "Te veel mislukte pogingen" | Wacht 15 minuten, of reset het wachtwoord met het commando hierboven. |
| Tijden kloppen niet | De container gebruikt `TZ=Europe/Amsterdam`. Pas dat alleen aan als je echt een andere tijdzone wilt. |

## Ontwikkelen

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATA_MAP=./data
flask --app wsgi:app db upgrade
flask --app wsgi:app setup-code
flask --app wsgi:app run --debug        # http://127.0.0.1:5000
pytest -q                               # tests
ruff check .                            # lint
```

Structuur:

```
app/                 Flask-app
  blueprints/        routes: auth, setup, beheer, rooster, kalender, overzicht, zoeken, deel
  services/          logica: urenberekening, kalender (ISO-weken/Pasen/feestdagen), ...
  templates/ static/ HTML, CSS, JavaScript (HTMX lokaal meegeleverd, geen CDN)
  models.py          datamodel (SQLAlchemy)
migrations/          databasemigraties (Alembic via Flask-Migrate)
docker/              entrypoint en Gunicorn-configuratie
tests/               pytest (alle testdata is fictief)
scripts/             proxmox-maak-lxc.sh
docs/                handleidingen (planner, collega, Proxmox)
```

Een nieuwe databasemigratie maak je na een wijziging in `models.py` met `flask --app wsgi:app db migrate -m "omschrijving"`.

## Handleidingen

- [Handleiding voor de planner](docs/handleiding-planner.md): een week invullen met het code-raster, toetsen, tijden, opmerkingen, beheer.
- [Handleiding voor collega's](docs/handleiding-collega.md): inloggen, rooster bekijken, printen, agenda.
- [Google Agenda koppelen](docs/google-agenda.md): service-account, modus A/B, ICS-feed.
- [Installatie op Proxmox](docs/proxmox-lxc.md): LXC aanmaken, Docker, HTTPS.

## Licentie

MIT, zie [LICENSE](LICENSE).
