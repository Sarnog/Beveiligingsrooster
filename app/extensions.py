"""Gedeelde Flask-extensies. Hier aangemaakt, in create_app() gekoppeld."""

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


@event.listens_for(Engine, "connect")
def _sqlite_instellingen(dbapi_verbinding, _verbinding_record):
    """Zet bij elke nieuwe SQLite-verbinding de juiste instellingen aan.

    - WAL-modus: lezen en schrijven tegelijk (meerdere Gunicorn-workers).
    - foreign_keys: SQLite controleert koppelingen tussen tabellen pas als dit aan staat.
    - busy_timeout: bij een vergrendelde database maximaal 5 seconden wachten.
    """
    if dbapi_verbinding.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_verbinding.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
