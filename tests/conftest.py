"""Gedeelde test-opzet. Alle testdata is fictief ('Medewerker A' enz.)."""

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import ROL_BEHEERDER, ROL_GEBRUIKER, Gebruiker
from app.services import instellingen
from app.services.wachtwoorden import hash_wachtwoord

from .browser_hulp import browser, server, sessies  # noqa: F401  (fixtures voor de browsertests)

WACHTWOORD = "testwachtwoord123"


class TestConfig(Config):
    def __init__(self, data_map: str) -> None:
        import os

        os.environ["DATA_MAP"] = data_map
        super().__init__()
        self.TESTING = True
        self.SECRET_KEY = "test-geheim"
        self.WTF_CSRF_ENABLED = False
        self.SQLALCHEMY_DATABASE_URI = f"sqlite:///{data_map}/test.db"


def _vergeet_ingelogde_gebruiker():
    """In de tests blijft één app-context open; in het echt krijgt elk verzoek een verse.

    Flask-Login bewaart de gebruiker in g (per app-context). Zonder dit zou elk verzoek de
    gebruiker van het vorige verzoek hergebruiken, en zie je uitloggen via de sessie niet.
    """
    from flask import g

    g.pop("_login_user", None)


@pytest.fixture(autouse=True)
def _geen_tussenpoze(monkeypatch):
    """De Google-klant wacht in het echt 1 s tussen aanroepen; in de tests niet."""
    from app.services import google_agenda

    monkeypatch.setattr(google_agenda, "TUSSENPOZE", 0)


@pytest.fixture
def app(tmp_path):
    app = create_app(TestConfig(str(tmp_path)))
    app.before_request_funcs.setdefault(None, []).insert(0, _vergeet_ingelogde_gebruiker)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()


@pytest.fixture
def gemigreerd(app):
    """Database via de echte migraties (zoals in productie), setup afgerond."""
    import os

    from flask_migrate import upgrade

    db.drop_all()
    upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))
    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def maak_gebruiker(gebruikersnaam: str, rol: str, **extra) -> Gebruiker:
    gebruiker = Gebruiker(
        gebruikersnaam=gebruikersnaam,
        weergavenaam=gebruikersnaam.title(),
        wachtwoord_hash=hash_wachtwoord(WACHTWOORD),
        rol=rol,
        **extra,
    )
    db.session.add(gebruiker)
    db.session.commit()
    return gebruiker


@pytest.fixture
def klaar(app):
    """Setup afgerond, met één beheerder en één gewone gebruiker."""
    instellingen.schrijf("setup_voltooid", "1")
    db.session.commit()
    beheerder = maak_gebruiker("beheerder", ROL_BEHEERDER)
    gebruiker = maak_gebruiker("collega", ROL_GEBRUIKER)
    return {"beheerder": beheerder, "gebruiker": gebruiker}


def login(client, gebruikersnaam: str, wachtwoord: str = WACHTWOORD):
    return client.post("/login", data={"gebruikersnaam": gebruikersnaam, "wachtwoord": wachtwoord})


@pytest.fixture
def als_beheerder(client, klaar):
    login(client, "beheerder")
    return client


@pytest.fixture
def als_gebruiker(client, klaar):
    login(client, "collega")
    return client
