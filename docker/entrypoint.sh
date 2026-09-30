#!/bin/sh
# Startscript van de container.
#   web    -> database bijwerken (migraties), setup-code tonen, Gunicorn starten
#   worker -> achtergrondtaken (agenda-sync, logboek opschonen, back-ups)
#   iets anders -> dat commando uitvoeren (bijv. "flask reset-wachtwoord naam")
set -e

# Nieuwe bestanden (database, back-ups) alleen leesbaar voor de app zelf
umask 027

# De datamap moet van de app-gebruiker (uid 1000) zijn. Docker maakt een
# nieuwe map als root aan, dus dat corrigeren we hier één keer.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_MAP"
    if [ "$(stat -c %u "$DATA_MAP")" != "1000" ]; then
        chown -R 1000:1000 "$DATA_MAP"
    fi
    chmod 750 "$DATA_MAP"
    # Verder als gewone gebruiker 'rooster' (nooit als root)
    export HOME=/home/rooster
    exec setpriv --reuid=1000 --regid=1000 --init-groups "$0" "$@"
fi

case "$1" in
    web)
        echo "Database bijwerken..."
        flask db upgrade
        # Toont de setup-code in de log zolang de setup niet is afgerond
        flask setup-code
        exec gunicorn --config /app/docker/gunicorn.conf.py wsgi:app
        ;;
    worker)
        exec python -m app.worker
        ;;
    *)
        exec "$@"
        ;;
esac
