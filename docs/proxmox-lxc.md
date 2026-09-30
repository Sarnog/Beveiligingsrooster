# Installatie op Proxmox (LXC met Docker)

In deze handleiding maak je een lichte LXC-container op Proxmox. Daarin installeer je Docker, en in Docker draait de app. Je kunt kiezen voor **Alpine** (kleinst) of **Debian** (bekendst). De app werkt op beide precies hetzelfde.

## Benodigdheden

| | Minimaal | Aanbevolen |
|---|---|---|
| vCPU | 1 | 1 |
| Geheugen | 512 MB | 1024 MB |
| Swap | 256 MB | 512 MB |
| Schijf | 4 GB | 8 GB |

Docker zelf gebruikt wat extra geheugen en schijfruimte (images). Daarom is 1 GB geheugen en 8 GB schijf prettiger dan het absolute minimum.

---

## Snelle weg: script op de Proxmox-host

Open op de Proxmox-host een shell (*Node → Shell*) en voer uit:

```sh
wget -qO- https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/scripts/proxmox-maak-lxc.sh | sh
```

Met opties (voorbeeld):

```sh
wget -qO /root/maak-lxc.sh https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/scripts/proxmox-maak-lxc.sh
CTID=150 OS=debian IP=192.168.1.50/24 GATEWAY=192.168.1.1 OPSLAG=local-lvm sh /root/maak-lxc.sh
```

| Variabele | Standaard | Betekenis |
|---|---|---|
| `CTID` | eerstvolgend vrij nummer | ID van de container |
| `OS` | `alpine` | `alpine` of `debian` |
| `GEHEUGEN` / `SWAP` | `1024` / `512` | in MB |
| `SCHIJF` | `8` | in GB |
| `OPSLAG` | `local-lvm` | opslag voor de schijf van de LXC |
| `IP` | `dhcp` | of een vast adres, bijvoorbeeld `192.168.1.50/24` (dan ook `GATEWAY`) |
| `BRUG` | `vmbr0` | netwerkbrug |

Het script doet het volgende:
1. het downloadt het nieuwste template;
2. het maakt een **unprivileged** LXC met `nesting=1,keyctl=1`;
3. het zet "starten bij opstarten" aan;
4. het draait daarna `install.sh` in de container.

Aan het eind zie je de URL en de setup-code.

---

## Stap voor stap (webinterface)

### 1. Template downloaden

*Node → local (opslag) → CT Templates → Templates*. Kies:
- **alpine-3.xx-default** (nieuwste versie), of
- **debian-12-standard** / **debian-13-standard**.

Klik op **Download**.

Via de shell van de host gaat het zo:

```sh
pveam update
pveam available --section system | grep -E 'alpine|debian'
pveam download local alpine-3.22-default_20250617_amd64.tar.xz   # naam uit de lijst hierboven
```

### 2. Container aanmaken

Klik op **Create CT** en vul in:

| Tabblad | Instelling |
|---|---|
| General | Hostname `beveiligingsrooster`, **Unprivileged container: aan**, wachtwoord voor root |
| Template | het gedownloade template |
| Disks | 8 GB |
| CPU | 1 core |
| Memory | 1024 MB, swap 512 MB |
| Network | `vmbr0`, IPv4 DHCP of een vast adres |
| DNS | standaard |

Zet onder **Confirm** nog niet "Start after created" aan.

### 3. Docker toestaan in de LXC (belangrijk)

*Container → Options → Features → Edit*: vink **Nesting** en **keyctl** aan.

Zet onder *Options → Start at boot* ook op **Yes**. Start daarna de container.

### 4. Installeren

Open de console van de container (*Container → Console*) en log in als root.

**Alpine:**
```sh
apk add curl
curl -fsSL https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/install.sh | sh
```

**Debian:**
```sh
apt-get update && apt-get install -y curl
curl -fsSL https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/install.sh | sh
```

Aan het eind zie je bijvoorbeeld:

```
==> Installatie klaar!
  Open in je browser:  http://192.168.1.50:8000/setup
  Setup-code:          ABCD-EFGH-JKLM
```

## Dezelfde container via de command line (`pct create`)

Dit doe je op de Proxmox-host:

```sh
pct create 150 local:vztmpl/alpine-3.22-default_20250617_amd64.tar.xz \
  --hostname beveiligingsrooster \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --cores 1 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --timezone Europe/Amsterdam \
  --onboot 1 --start 1

pct exec 150 -- sh -c "apk add --no-cache curl && curl -fsSL https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/install.sh | sh"
```

Een vast IP-adres: `--net0 name=eth0,bridge=vmbr0,ip=192.168.1.50/24,gw=192.168.1.1`.

---

## Wat staat waar?

| Pad (in de LXC) | Inhoud |
|---|---|
| `/opt/beveiligingsrooster/docker-compose.yml` | welke containers er draaien |
| `/opt/beveiligingsrooster/.env` | jouw instellingen (poort, BASE_URL, …) |
| `/opt/beveiligingsrooster/data/` | **alle data**: database, back-ups, geheime sleutel |
| `/opt/beveiligingsrooster/update.sh` | bijwerken (maakt eerst een back-up) |
| `/opt/beveiligingsrooster/uninstall.sh` | verwijderen (vraagt of de data mag blijven) |

Logs bekijk je met `cd /opt/beveiligingsrooster && docker compose logs -f`. Docker start de containers zelf opnieuw na een herstart van de LXC (`restart: unless-stopped`), dus er zijn geen losse OpenRC- of systemd-services nodig.

## Back-up met Proxmox

De app maakt zelf elke nacht een database-back-up. Laat Proxmox daarnaast de hele LXC back-uppen: *Datacenter → Backup → Add*, kies de container, een schema (bijvoorbeeld dagelijks 03:00) en modus **Snapshot**. Zo kun je bij een defecte schijf alles in één keer terugzetten.

---

## HTTPS en bereikbaarheid

Je hebt drie mogelijkheden.

### (a) Alleen in het LAN

Dit is de standaard. De app luistert op `http://<ip-van-de-lxc>:8000`. Je hoeft niets in te stellen.

### (b) Reverse proxy met Caddy (automatisch HTTPS)

Caddy vraagt zelf een Let's Encrypt-certificaat aan. Daarvoor heb je nodig:
- een domeinnaam die naar je publieke IP wijst;
- poort 80 en 443 doorgestuurd naar de LXC.

1. Laat de app alleen lokaal luisteren en vertel hem dat er een proxy voor staat. Zet in `/opt/beveiligingsrooster/.env`:
   ```
   LUISTER_ADRES=127.0.0.1
   BASE_URL=https://rooster.voorbeeld.nl
   PROXY_VERTROUWEN=1
   ```
2. Installeer Caddy in de LXC:
   - Alpine: `apk add caddy && rc-update add caddy default`
   - Debian: `apt-get install -y caddy`
3. Zet in `/etc/caddy/Caddyfile` (voorbeeld: [Caddyfile.voorbeeld](Caddyfile.voorbeeld)):
   ```
   rooster.voorbeeld.nl {
       reverse_proxy 127.0.0.1:8000
   }
   ```
4. Herstart:
   ```sh
   cd /opt/beveiligingsrooster && docker compose up -d
   ```
   en daarna, afhankelijk van het OS:
   - Alpine: `rc-service caddy restart`
   - Debian: `systemctl restart caddy`

### (c) Tunnel: Cloudflare Tunnel of Tailscale (geen poorten openzetten)

- **Cloudflare Tunnel:**
  1. Maak in het Cloudflare-dashboard (*Zero Trust → Networks → Tunnels*) een tunnel aan.
  2. Installeer `cloudflared` in de LXC met het commando dat Cloudflare toont.
  3. Voeg een *Public hostname* toe die wijst naar `http://127.0.0.1:8000`.
- **Tailscale:**
  1. Installeer Tailscale in de LXC. Voor een unprivileged LXC is `/dev/net/tun` nodig; zie de handleiding van Tailscale voor LXC.
  2. Gebruik daarna `tailscale serve` of *Funnel* voor HTTPS.

Zet in beide gevallen `BASE_URL=https://…` en `PROXY_VERTROUWEN=1` in `.env`, en voer daarna `docker compose up -d` uit.

**Google Agenda (API-koppeling)** heeft alleen **uitgaand** internet nodig; dat werkt met elke optie. De **ICS-feed** moet door Google opgehaald kunnen worden. Die werkt dus alleen met (b) of (c).
