#!/bin/sh
# ==========================================================
# Beveiligingsrooster – verwijderen
#
#   cd /opt/beveiligingsrooster && ./uninstall.sh
#
# Stopt en verwijdert de containers en de image. Vraagt of de data
# (database, back-ups, sleutels) bewaard moet blijven. Docker zelf blijft staan.
# ==========================================================
set -eu

cd "$(dirname "$0")"
MAP="$(pwd)"

COMPOSE="docker compose"
[ -f docker-compose.bouwen.yml ] && COMPOSE="docker compose -f docker-compose.yml -f docker-compose.bouwen.yml"

# Vraag via de terminal (werkt ook als het script via een pipe gestart is)
printf "Data (database en back-ups in %s/data) BEWAREN? [J/n] " "$MAP"
read -r antwoord < /dev/tty || antwoord="j"

echo "==> Containers stoppen en verwijderen"
$COMPOSE down --rmi all || true

case "$antwoord" in
    n|N|nee|Nee)
        printf "Weet je het zeker? ALLE roosterdata wordt verwijderd. Typ 'verwijder': "
        read -r zeker < /dev/tty || zeker=""
        if [ "$zeker" = "verwijder" ]; then
            cd /
            rm -rf "$MAP"
            echo "Alles is verwijderd."
        else
            echo "Afgebroken: de data staat nog in $MAP/data."
        fi
        ;;
    *)
        rm -f "$MAP/docker-compose.bouwen.yml"
        rm -rf "$MAP/bron"
        echo "De app is verwijderd. Je data staat nog in $MAP/data (en instellingen in $MAP/.env)."
        echo "Opnieuw installeren met install.sh pakt deze data automatisch weer op."
        ;;
esac
