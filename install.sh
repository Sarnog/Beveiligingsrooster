#!/bin/sh
# ==========================================================
# Beveiligingsrooster – installatie in een LXC (Alpine of Debian)
#
# Uitvoeren als root in de container:
#   wget -qO- https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main/install.sh | sh
#
# Wat dit script doet (veilig om vaker te draaien):
#   1. Docker + Docker Compose installeren en bij het opstarten laten starten
#   2. Tijdzone op Europe/Amsterdam zetten
#   3. /opt/beveiligingsrooster aanmaken met docker-compose.yml en .env
#   4. De app starten (kant-en-klare image, of zelf bouwen als dat niet lukt)
#   5. De setup-code en het adres tonen
#
# Instelbaar via omgevingsvariabelen, bijvoorbeeld:
#   INSTALL_MAP=/opt/rooster POORT=8080 sh install.sh
# ==========================================================
set -eu

INSTALL_MAP="${INSTALL_MAP:-/opt/beveiligingsrooster}"
REPO_URL="${REPO_URL:-https://github.com/Sarnog/Beveiligingsrooster.git}"
RAW_URL="${RAW_URL:-https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main}"
POORT="${POORT:-8000}"
LUISTER_ADRES="${LUISTER_ADRES:-0.0.0.0}"
BOUW_LOKAAL="${BOUW_LOKAAL:-0}"   # 1 = altijd zelf bouwen uit de broncode

melding() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
fout() { printf '\n\033[1;31mFOUT: %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" = "0" ] || fout "Voer dit script uit als root."
[ -r /etc/os-release ] || fout "Onbekend besturingssysteem (geen /etc/os-release)."
. /etc/os-release
OS="${ID:-onbekend}"

# ---------- 1. Docker installeren ----------
melding "Docker installeren (besturingssysteem: $OS)"
case "$OS" in
    alpine)
        apk update
        apk add docker docker-cli-compose curl tzdata git
        rc-update add docker default >/dev/null 2>&1 || true
        rc-service docker start || true
        ;;
    debian|ubuntu)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y ca-certificates curl tzdata git
        if ! command -v docker >/dev/null 2>&1; then
            # Officieel installatiescript van Docker (docker-ce + compose-plugin)
            curl -fsSL https://get.docker.com | sh
        fi
        systemctl enable --now docker >/dev/null 2>&1 || service docker start || true
        ;;
    *)
        fout "Dit script ondersteunt Alpine en Debian/Ubuntu. Installeer Docker handmatig en volg de README."
        ;;
esac

# Wachten tot de Docker-daemon draait
i=0
until docker info >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 30 ] && fout "Docker start niet. Staat 'nesting' (en 'keyctl') aan bij de LXC? Zie docs/proxmox-lxc.md."
    sleep 1
done
docker compose version >/dev/null 2>&1 || fout "Docker Compose ontbreekt."

# ---------- 2. Tijdzone ----------
melding "Tijdzone op Europe/Amsterdam zetten"
if [ -f /usr/share/zoneinfo/Europe/Amsterdam ]; then
    ln -sf /usr/share/zoneinfo/Europe/Amsterdam /etc/localtime
    echo "Europe/Amsterdam" > /etc/timezone
fi

# ---------- 3. Bestanden klaarzetten ----------
melding "Map $INSTALL_MAP klaarzetten"
mkdir -p "$INSTALL_MAP/data"
cd "$INSTALL_MAP"

if [ ! -f docker-compose.yml ]; then
    curl -fsSL "$RAW_URL/docker-compose.yml" -o docker-compose.yml \
        || fout "Kan docker-compose.yml niet downloaden van $RAW_URL"
fi
if [ ! -f .env ]; then
    # .env bewaart jouw instellingen; wordt nooit overschreven
    cat > .env <<EOF
LUISTER_ADRES=$LUISTER_ADRES
POORT=$POORT
BASE_URL=
PROXY_VERTROUWEN=0
SESSIE_UREN=12
SECRET_KEY=
EOF
    chmod 600 .env
fi
# Beheerscripts erbij zetten (handig voor later)
for script in update.sh uninstall.sh; do
    curl -fsSL "$RAW_URL/$script" -o "$script" 2>/dev/null && chmod +x "$script" || true
done

# ---------- 4. Starten ----------
COMPOSE="docker compose"
bouw_zelf() {
    melding "Image zelf bouwen uit de broncode"
    if [ -d bron/.git ]; then
        git -C bron pull --ff-only
    else
        git clone --depth 1 "$REPO_URL" bron
    fi
    cp bron/docker-compose.bouwen.yml docker-compose.bouwen.yml
    sed -i 's#build: \.#build: ./bron#' docker-compose.bouwen.yml
    COMPOSE="docker compose -f docker-compose.yml -f docker-compose.bouwen.yml"
    $COMPOSE build
}

if [ "$BOUW_LOKAAL" = "1" ] || [ -f docker-compose.bouwen.yml ]; then
    bouw_zelf
else
    melding "Kant-en-klare image downloaden"
    if ! docker compose pull; then
        echo "Downloaden lukt niet (is het GitHub-pakket openbaar?). We bouwen de image zelf."
        bouw_zelf
    fi
fi

melding "App starten"
$COMPOSE up -d

# Wachten tot de app gezond is
i=0
until curl -fsS "http://127.0.0.1:$POORT/health" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -gt 90 ] && fout "De app reageert niet. Bekijk de logs: cd $INSTALL_MAP && docker compose logs"
    sleep 2
done

# ---------- 5. Klaar ----------
IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')"
[ -n "$IP" ] || IP="<ip-van-de-lxc>"
CODE="$($COMPOSE exec -T -u rooster web flask setup-code 2>/dev/null | sed -n 's/^Setup-code: //p')"

melding "Installatie klaar!"
echo "  Open in je browser:  http://$IP:$POORT/setup"
if [ -n "$CODE" ]; then
    echo "  Setup-code:          $CODE"
else
    echo "  De setup is al afgerond (of vraag de code op: cd $INSTALL_MAP && docker compose exec -u rooster web flask setup-code)"
fi
echo
echo "  Map:        $INSTALL_MAP  (data in $INSTALL_MAP/data)"
echo "  Logs:       cd $INSTALL_MAP && docker compose logs -f"
echo "  Bijwerken:  cd $INSTALL_MAP && ./update.sh"
