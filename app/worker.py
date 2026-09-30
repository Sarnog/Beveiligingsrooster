"""Achtergrondworker: één eenvoudige lus, draait in een eigen container.

Gekozen voor een eigen lus in plaats van APScheduler: geen extra afhankelijkheid
en makkelijk te volgen. Elke ronde (elke paar seconden):
- Google Agenda-wachtrij verwerken (fase 3)
- één keer per dag: logboek opschonen
- één keer per nacht (na 02:00): back-up maken (fase 4)

Starten: python -m app.worker
"""

import logging
import time
from datetime import date, datetime

from . import create_app
from .services import instellingen, klok, logboek

log = logging.getLogger("worker")
INTERVAL_SECONDEN = 5
BACKUP_UUR = 2  # back-up na 02:00 's nachts


class Planning:
    """Onthoudt wanneer de dagelijkse taken voor het laatst gedraaid hebben."""

    def __init__(self) -> None:
        self.opschonen_gedaan: date | None = None
        self.backup_gedaan: date | None = None


def een_ronde(planning: Planning, nu: datetime | None = None) -> None:
    """Voer één ronde van de worker uit (los aan te roepen in tests)."""
    nu = nu or klok.nu()

    # 1. Agenda-synchronisatie
    try:
        from .services import sync

        sync.verwerk_wachtrij()
    except ImportError:
        pass  # sync bestaat nog niet (fase 3)

    if not instellingen.setup_voltooid():
        return

    # 2. Logboek dagelijks opschonen
    if planning.opschonen_gedaan != nu.date():
        aantal = logboek.opschonen(nu)
        log.info("Logboek opgeschoond: %s regels verwijderd", aantal)
        planning.opschonen_gedaan = nu.date()

    # 3. Nachtelijke back-up
    if nu.hour >= BACKUP_UUR and planning.backup_gedaan != nu.date():
        try:
            from .services import backup

            pad = backup.maak_backup()
            backup.ruim_oude_op()
            log.info("Back-up gemaakt: %s", pad)
        except ImportError:
            pass  # back-ups komen in fase 4
        planning.backup_gedaan = nu.date()


def main() -> None:
    app = create_app()
    planning = Planning()
    log.info("Worker gestart")
    with app.app_context():
        while True:
            try:
                een_ronde(planning)
            except Exception:  # noqa: BLE001 - worker mag nooit stoppen door één fout
                log.exception("Fout in worker-ronde")
                from .extensions import db

                db.session.rollback()
            finally:
                # Sessie opruimen zodat we steeds verse data uit de database lezen
                from .extensions import db

                db.session.remove()
            time.sleep(INTERVAL_SECONDEN)


if __name__ == "__main__":
    main()
