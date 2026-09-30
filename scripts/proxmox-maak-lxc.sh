#!/bin/sh
# ==========================================================
# Beveiligingsrooster – LXC aanmaken op de Proxmox-HOST
#
# Draai dit op de Proxmox-host (niet in een container), als root:
#   sh proxmox-maak-lxc.sh
#
# Instelbaar via omgevingsvariabelen, bijvoorbeeld:
#   CTID=150 OS=debian OPSLAG=local-lvm IP=192.168.1.50/24 GATEWAY=192.168.1.1 sh proxmox-maak-lxc.sh
#
# Maakt een unprivileged LXC met 'nesting' en 'keyctl' aan (nodig voor Docker),
# start hem bij het opstarten van Proxmox en installeert daarna de app.
# ==========================================================
set -eu

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
OS="${OS:-alpine}"                 # alpine of debian
HOSTNAAM="${HOSTNAAM:-beveiligingsrooster}"
KERNEN="${KERNEN:-1}"
GEHEUGEN="${GEHEUGEN:-1024}"       # MB (Docker + app; 512 kan, 1024 is ruimer)
SWAP="${SWAP:-512}"
SCHIJF="${SCHIJF:-8}"              # GB
OPSLAG="${OPSLAG:-local-lvm}"      # waar de schijf van de LXC komt
TEMPLATE_OPSLAG="${TEMPLATE_OPSLAG:-local}"
BRUG="${BRUG:-vmbr0}"
IP="${IP:-dhcp}"                   # dhcp of bijv. 192.168.1.50/24
GATEWAY="${GATEWAY:-}"
RAW_URL="${RAW_URL:-https://raw.githubusercontent.com/Sarnog/Beveiligingsrooster/main}"

command -v pct >/dev/null 2>&1 || { echo "FOUT: dit script hoort op de Proxmox-host." >&2; exit 1; }

echo "==> Templatelijst bijwerken"
pveam update >/dev/null

# Nieuwste template van het gekozen OS zoeken
case "$OS" in
    alpine) PATROON='alpine-[0-9.]+-default' ;;
    debian) PATROON='debian-[0-9]+-standard' ;;
    *) echo "FOUT: OS moet alpine of debian zijn." >&2; exit 1 ;;
esac
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E "^$PATROON" | sort -V | tail -n 1)"
[ -n "$TEMPLATE" ] || { echo "FOUT: geen $OS-template gevonden." >&2; exit 1; }

if ! pveam list "$TEMPLATE_OPSLAG" | grep -q "$TEMPLATE"; then
    echo "==> Template downloaden: $TEMPLATE"
    pveam download "$TEMPLATE_OPSLAG" "$TEMPLATE"
fi

NET="name=eth0,bridge=$BRUG,ip=$IP"
[ -n "$GATEWAY" ] && NET="$NET,gw=$GATEWAY"

echo "==> LXC $CTID aanmaken ($OS, $KERNEN vCPU, $GEHEUGEN MB, $SCHIJF GB)"
pct create "$CTID" "$TEMPLATE_OPSLAG:vztmpl/$TEMPLATE" \
    --hostname "$HOSTNAAM" \
    --unprivileged 1 \
    --features nesting=1,keyctl=1 \
    --cores "$KERNEN" --memory "$GEHEUGEN" --swap "$SWAP" \
    --rootfs "$OPSLAG:$SCHIJF" \
    --net0 "$NET" \
    --timezone Europe/Amsterdam \
    --onboot 1 \
    --start 1

echo "==> Wachten op netwerk in de container"
sleep 8

echo "==> Beveiligingsrooster installeren in de container"
if [ "$OS" = "alpine" ]; then
    pct exec "$CTID" -- sh -c "apk add --no-cache curl >/dev/null && curl -fsSL $RAW_URL/install.sh | sh"
else
    pct exec "$CTID" -- sh -c "apt-get update >/dev/null && apt-get install -y curl >/dev/null && curl -fsSL $RAW_URL/install.sh | sh"
fi
