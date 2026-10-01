"""Achtergrondworker: één eenvoudige lus, draait in een eigen container.

Gekozen voor een eigen lus in plaats van APScheduler: geen extra afhankelijkheid
en makkelijk te volgen. Elke ronde (elke paar seconden):
- de Google Agenda-wachtrij verwerken;
- één keer per dag: logboek, oude loginpogingen en achtergebleven importbestanden opruimen;
- één keer per nacht (na 02:00): een back-up maken en oude back-ups opruimen.

Elke stap heeft een eigen foutafhandeling: een fout in de agenda-sync houdt de
back-up dus niet tegen (en andersom). Mislukt de back-up, dan probeert de worker
het pas na BACKUP_BACKOFF opnieuw (niet elke ronde), met een regel in het logboek.

Stoppen: SIGTERM (docker stop) of SIGINT (Ctrl+C). De lopende ronde (bijv. een sync of
back-up) wordt eerst afgemaakt; daarna stopt de lus netjes, binnen de 10 s van docker stop.

Starten: python -m app.worker
"""

import logging
import signal
import threading
from datetime import date, datetime, timedelta

from . import create_app, debuglog
from .extensions import db
from .services import instellingen, klok, logboek

log = logging.getLogger("worker")
INTERVAL_SECONDEN = 5
BACKUP_UUR = 2  # back-up na 02:00 's nachts
BACKUP_BACKOFF = timedelta(minutes=30)  # wachttijd na een mislukte back-up


class Planning:
    """Onthoudt wanneer de dagelijkse taken voor het laatst gedraaid hebben."""

    def __init__(self) -> None:
        self.opschonen_gedaan: date | None = None
        self.backup_gedaan: date | None = None
        self.backup_niet_voor: datetime | None = None  # backoff na een mislukte back-up


def _stap_sync() -> None:
    from .services import sync

    sync.verwerk_wachtrij()


def _stap_opschonen(nu: datetime) -> None:
    from .services import excel_import

    aantal = logboek.opschonen(nu)
    pogingen = logboek.ruim_loginpogingen_op()
    bestanden = excel_import.ruim_oude_uploads_op()
    log.info("Opgeschoond: %s logboekregels, %s loginpogingen, %s importbestanden",
             aantal, pogingen, bestanden)


def _stap_backup(planning: Planning, nu: datetime) -> None:
    from .services import backup

    try:
        pad = backup.maak_backup()
    except Exception as fout:  # nooit elke ronde opnieuw proberen
        planning.backup_niet_voor = nu + BACKUP_BACKOFF
        log.exception("Back-up mislukt; volgende poging na %s", planning.backup_niet_voor)
        db.session.rollback()
        try:
            logboek.log("Back-up mislukt", f"{type(fout).__name__}: {fout}", gebruiker="systeem")
            db.session.commit()
        except Exception:  # bijv. de schijf is vol
            db.session.rollback()
        return
    planning.backup_gedaan = nu.date()
    planning.backup_niet_voor = None
    log.info("Back-up gemaakt: %s", pad)
    try:
        backup.ruim_oude_op()
        backup.ruim_gelabelde_op()
    except Exception:  # de back-up zelf is gelukt; opruimen kan morgen weer
        log.exception("Oude back-ups opruimen mislukt")


def een_ronde(planning: Planning, nu: datetime | None = None) -> None:
    """Voer één ronde van de worker uit (los aan te roepen in tests)."""
    nu = nu or klok.nu()
    try:
        from flask import current_app

        from . import debuglog

        debuglog.ververs(current_app._get_current_object())  # logniveau gewijzigd in Beheer?
        if debuglog.roteer(current_app.config["DATA_MAP"]):
            log.info("Debuglog geroteerd")
    except Exception:  # loggen mag de worker nooit stilleggen
        log.exception("Debuglog roteren mislukt")

    # 1. Agenda-synchronisatie
    try:
        _stap_sync()
    except Exception:  # een sync-fout mag de rest niet tegenhouden
        log.exception("Fout in de agenda-synchronisatie")
        db.session.rollback()

    if not instellingen.setup_voltooid():
        return

    # 2. Dagelijks opschonen (bij een fout: morgen opnieuw)
    if planning.opschonen_gedaan != nu.date():
        planning.opschonen_gedaan = nu.date()
        try:
            _stap_opschonen(nu)
        except Exception:
            log.exception("Fout bij het opschonen")
            db.session.rollback()

    # 3. Nachtelijke back-up (na een fout: pas na de backoff opnieuw)
    if nu.hour >= BACKUP_UUR and planning.backup_gedaan != nu.date() \
            and (planning.backup_niet_voor is None or nu >= planning.backup_niet_voor):
        _stap_backup(planning, nu)


def main() -> None:
    app = create_app()
    planning = Planning()
    stoppen = threading.Event()

    def stop_signaal(signum, _frame) -> None:
        # Alleen een vlag zetten: de lopende ronde mag afmaken wat hij doet
        log.info("Signaal %s ontvangen: worker stopt na de lopende ronde", signal.Signals(signum).name)
        stoppen.set()

    signal.signal(signal.SIGTERM, stop_signaal)
    signal.signal(signal.SIGINT, stop_signaal)
    stand = debuglog.stand(app)
    log.info("Worker gestart (log: %s%s)", stand["niveau"], ", debuglog aan" if stand["aan"] else "")
    with app.app_context():
        while not stoppen.is_set():
            try:
                een_ronde(planning)
            except Exception:  # worker mag nooit stoppen door één fout
                log.exception("Fout in worker-ronde")
                db.session.rollback()
            finally:
                # Sessie opruimen zodat we steeds verse data uit de database lezen
                db.session.remove()
            stoppen.wait(INTERVAL_SECONDEN)  # wordt direct wakker bij een stopsignaal
    log.info("Worker gestopt")


if __name__ == "__main__":
    main()
