#!/bin/sh
# Rooktest van de Docker-image: start web en worker op een LEGE datamap en controleert
# dat alles werkt, inclusief docker/entrypoint.sh (chown, setpriv, umask).
#
#   sh scripts/docker-rooktest.sh [image]        (standaard: beveiligingsrooster:rooktest)
#
# Bouw de image eerst, bijvoorbeeld: docker build -t beveiligingsrooster:rooktest .
# Draait ook in CI (job 'docker-rooktest'). Ruimt zijn containers en datamap zelf op.
set -eu

IMAGE="${1:-beveiligingsrooster:rooktest}"
WEB=rooktest-web
WORKER=rooktest-worker
POORT="${ROOKTEST_POORT:-18000}"
DATA="$(mktemp -d)"
# Zoals Docker een nieuwe map aanmaakt: van root (entrypoint moet hem overnemen)
chmod 755 "$DATA"

stap() { echo; echo "=== $*"; }
fout() { echo "FOUT: $*" >&2; docker logs "$WEB" 2>&1 | tail -40 >&2 || true; exit 1; }

opruimen() {
    docker rm -f "$WEB" "$WORKER" >/dev/null 2>&1 || true
    # Bestanden in de datamap zijn van uid 1000; via een container weggooien
    docker run --rm -u root --entrypoint sh -v "$DATA:/data" "$IMAGE" -c 'rm -rf /data/* /data/.[!.]*' \
        >/dev/null 2>&1 || true
    rm -rf "$DATA" 2>/dev/null || true
}
trap opruimen EXIT
opruimen_vooraf() { docker rm -f "$WEB" "$WORKER" >/dev/null 2>&1 || true; }
opruimen_vooraf

# Python in de web-container, als de app-gebruiker en met een app-context
py() { docker exec -i -u rooster "$WEB" python -; }

stap "Web-container starten met een lege /data ($IMAGE)"
docker run -d --name "$WEB" -p "127.0.0.1:$POORT:8000" -v "$DATA:/data" "$IMAGE" web >/dev/null

stap "Wachten tot /health 200 geeft"
i=0
until [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$POORT/health" || true)" = "200" ]; do
    i=$((i + 1))
    [ "$i" -le 60 ] || fout "/health gaf na 60 seconden nog geen 200"
    [ "$(docker inspect -f '{{.State.Running}}' "$WEB")" = "true" ] || fout "web-container is gestopt"
    sleep 1
done
echo "OK: /health = 200 na ${i}s"

stap "Setup-code staat in de log"
docker logs "$WEB" 2>&1 | grep -q "Setup-code: " || fout "geen setup-code in de log"
echo "OK"

stap "Entrypoint: datamap van uid 1000, rechten 750, app draait niet als root"
[ "$(docker exec "$WEB" stat -c '%u %a' /data)" = "1000 750" ] || fout "datamap: $(docker exec "$WEB" stat -c '%u %a' /data)"
uid=$(docker exec "$WEB" sh -c "awk '/^Uid:/ {print \$2}' /proc/1/status")
[ "$uid" = "1000" ] || fout "hoofdproces draait als uid $uid in plaats van 1000"
# umask 027: de database is niet leesbaar voor 'anderen'
rechten=$(docker exec "$WEB" stat -c '%a' /data/rooster.db)
case "$rechten" in *0) ;; *) fout "rooster.db heeft rechten $rechten (verwacht: geen rechten voor anderen)" ;; esac
echo "OK: /data = 1000 750, uid 1000, rooster.db = $rechten"

stap "Worker-container starten"
docker run -d --name "$WORKER" -v "$DATA:/data" "$IMAGE" worker >/dev/null
i=0
until docker logs "$WORKER" 2>&1 | grep -q "Worker gestart"; do
    i=$((i + 1))
    [ "$i" -le 30 ] || { docker logs "$WORKER" >&2; fout "geen 'Worker gestart' in de log van de worker"; }
    sleep 1
done
uid=$(docker exec "$WORKER" sh -c "awk '/^Uid:/ {print \$2}' /proc/1/status")
[ "$uid" = "1000" ] || fout "worker draait als uid $uid"
echo "OK: Worker gestart (uid 1000)"

stap "Back-up maken met flask backup (docker exec -u rooster)"
uitvoer=$(docker exec -u rooster "$WEB" flask backup --label rooktest)
echo "$uitvoer"
naam=$(basename "$(echo "$uitvoer" | sed -n 's/^Back-up gemaakt: //p')")
[ -n "$naam" ] && docker exec "$WEB" test -s "/data/backups/$naam" || fout "back-upbestand ontbreekt"

stap "Back-up/terugzetten-ronde: wijzigen, terugzetten, wijziging weg"
py <<'PY' || fout "wijziging maken mislukt"
from wsgi import app
from app.extensions import db
from app.models import Medewerker
with app.app_context():
    db.session.add(Medewerker(naam="Rooktest Na Backup", initialen="RNB"))
    db.session.commit()
    assert Medewerker.query.filter_by(initialen="RNB").count() == 1
PY
docker exec -u rooster "$WEB" flask terugzetten "$naam" --yes || fout "terugzetten mislukt"
py <<'PY' || fout "de wijziging staat er na het terugzetten nog"
from wsgi import app
from app.models import Medewerker
with app.app_context():
    assert Medewerker.query.filter_by(initialen="RNB").count() == 0
PY
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$POORT/health")" = "200" ] \
    || fout "/health na het terugzetten niet meer 200"
curl -s "http://127.0.0.1:$POORT/login" | grep -q "<form" || fout "loginpagina werkt niet na terugzetten"
[ "$(docker inspect -f '{{.State.Running}}' "$WORKER")" = "true" ] || fout "worker is gestopt"
docker exec "$WEB" sh -c 'ls /data/backups' | grep -q -- "-voor-terugzetten.db" || fout "geen veiligheidsback-up"
echo "OK: wijziging weg, app en worker draaien door"

stap "Geen fouten (Traceback) in de logs"
if docker logs "$WEB" 2>&1 | grep -q Traceback || docker logs "$WORKER" 2>&1 | grep -q Traceback; then
    docker logs "$WORKER" >&2
    fout "Traceback in de log"
fi
echo "OK"

echo
echo "Rooktest geslaagd."
