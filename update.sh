#!/bin/sh
# ==========================================================
# Beveiligingsrooster – bijwerken naar de nieuwste versie
#
# Uitvoeren als root in de installatiemap:
#   cd /opt/beveiligingsrooster && ./update.sh
#
# 1. Eerst een back-up van de database (data/backups/...-voor-update.db)
# 2. Nieuwe image ophalen (of opnieuw bouwen als je zelf bouwt)
# 3. Containers herstarten; databasemigraties draaien automatisch bij het starten
# Je data (./data) en instellingen (.env) blijven altijd ongemoeid.
# ==========================================================
set -eu

cd "$(dirname "$0")"
[ -f docker-compose.yml ] || { echo "FOUT: geen docker-compose.yml in $(pwd)" >&2; exit 1; }

COMPOSE="docker compose"
if [ -f docker-compose.bouwen.yml ]; then
    COMPOSE="docker compose -f docker-compose.yml -f docker-compose.bouwen.yml"
fi

echo "==> Back-up maken"
if $COMPOSE ps --status running --services 2>/dev/null | grep -qx web; then
    $COMPOSE exec -T -u rooster web flask backup --label voor-update
else
    echo "    (app draait niet; back-up overgeslagen, database blijft ongewijzigd in ./data)"
fi

if [ -f docker-compose.bouwen.yml ]; then
    echo "==> Broncode bijwerken en opnieuw bouwen"
    git -C bron pull --ff-only
    $COMPOSE build --pull
else
    echo "==> Nieuwe image downloaden"
    $COMPOSE pull
fi

echo "==> Herstarten"
$COMPOSE up -d

echo "==> Oude images opruimen"
docker image prune -f >/dev/null

echo "Klaar. Bekijk de logs met: $COMPOSE logs -f"
