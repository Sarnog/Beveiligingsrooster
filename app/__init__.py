"""Beveiligingsrooster: Flask-app.

create_app() bouwt de app op: configuratie, database, login, blueprints en de
controles die bij elk verzoek draaien (setup-wizard, rechten, security-headers).
"""

import logging
import os

from flask import Flask, abort, redirect, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager, migrate

VERSIE = "1.2.0"

# Deze endpoints mogen ook zonder afgeronde setup bereikbaar zijn
SETUP_VRIJ = {"static", "algemeen.health", "auth.login", "auth.uitloggen"}

# Deze endpoints zijn openbaar (geen login nodig); ze controleren zelf een geheim token
OPENBAAR = {"static", "algemeen.health"}

# Schrijvende endpoints die een gewone gebruiker WEL mag gebruiken
GEBRUIKER_MAG_SCHRIJVEN = {
    "auth.login",
    "auth.uitloggen",
    "auth.wachtwoord_wijzigen",
}


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config or Config())

    # Datamap aanmaken (database, back-ups, service-account)
    os.makedirs(app.config["DATA_MAP"], exist_ok=True)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _lees_of_maak_geheime_sleutel(app.config["DATA_MAP"])

    # Achter een reverse proxy: vertrouw X-Forwarded-For/Proto/Host van één proxy
    if app.config.get("PROXY_VERTROUWEN"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch nodig voor SQLite
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Log in om verder te gaan."
    login_manager.login_message_category = "info"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    _registreer_blueprints(app)
    _registreer_controles(app)
    _registreer_template_helpers(app)

    from .cli import registreer_commando_s

    registreer_commando_s(app)
    return app


def _lees_of_maak_geheime_sleutel(data_map: str) -> str:
    """Geen SECRET_KEY opgegeven? Dan maken we er zelf één en bewaren die in de datamap.

    Zo werkt een gekopieerd docker-compose-bestand zonder dat je zelf een geheim
    hoeft te verzinnen. Het bestand is alleen leesbaar voor de app (chmod 600).
    """
    import secrets

    pad = os.path.join(data_map, "secret_key")
    try:
        if os.path.exists(pad):
            with open(pad, encoding="utf-8") as bestand:
                sleutel = bestand.read().strip()
            if sleutel:
                return sleutel
        sleutel = secrets.token_hex(32)
        descriptor = os.open(pad, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as bestand:
            bestand.write(sleutel + "\n")
    except PermissionError as fout:
        raise RuntimeError(rechten_melding(pad)) from fout
    return sleutel


def rechten_melding(pad: str) -> str:
    """Uitleg bij een PermissionError op een bestand in de datamap."""
    return (f"Geen toegang tot {pad}. Waarschijnlijk is een commando zonder '-u rooster' "
            "uitgevoerd, waardoor het bestand van root is. Gebruik altijd "
            "'docker compose exec -u rooster web flask ...' en herstel de rechten met: "
            "docker compose run --rm -u root web chown -R 1000:1000 /data")


def _registreer_blueprints(app: Flask) -> None:
    from .blueprints import (
        algemeen,
        auth,
        beheer,
        deel,
        ics,
        kalender,
        overzicht,
        rooster,
        setup,
        zoeken,
    )

    for module in (algemeen, auth, setup, beheer, kalender, rooster, overzicht, zoeken, deel, ics):
        app.register_blueprint(module.bp)


def _registreer_controles(app: Flask) -> None:
    from .models import Gebruiker
    from .services import instellingen

    @login_manager.user_loader
    def laad_gebruiker(sessiesleutel: str):
        """Gebruiker uit de sessie, alleen als die sessie nog geldig is (zie Gebruiker.get_id).

        Ongeldig na wachtwoord wijzigen/resetten, deactiveren of terugzetten van een
        back-up; ook het oude formaat (alleen het ID, vóór 1.2.0) is ongeldig.
        """
        delen = (sessiesleutel or "").split(":")
        if len(delen) != 3 or not delen[0].isascii() or not delen[0].isdecimal():
            return None
        gebruiker = db.session.get(Gebruiker, int(delen[0]))
        if gebruiker is None or not gebruiker.actief or gebruiker.get_id() != sessiesleutel:
            return None
        return gebruiker

    @app.before_request
    def controleer_toegang():
        endpoint = request.endpoint or ""

        # 1. Setup nog niet afgerond: alles naar de setup-wizard
        if not instellingen.setup_voltooid():
            if endpoint in SETUP_VRIJ or endpoint.startswith("setup."):
                return None
            return redirect(url_for("setup.start"))

        if endpoint in OPENBAAR or endpoint.startswith(("deel.", "ics.")):
            return None

        # 2. Wachtwoord moet gewijzigd worden: eerst dat
        if (
            current_user.is_authenticated
            and current_user.moet_wachtwoord_wijzigen
            and endpoint not in ("auth.wachtwoord_wijzigen", "auth.uitloggen")
        ):
            return redirect(url_for("auth.wachtwoord_wijzigen"))

        # 3. Rechten server-side: een gewone gebruiker mag nooit iets wijzigen.
        #    Elke schrijvende methode (POST/PUT/PATCH/DELETE) is voor gebruikers
        #    verboden, behalve de expliciet toegestane endpoints hierboven.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if endpoint in GEBRUIKER_MAG_SCHRIJVEN:
                return None
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.is_beheerder:
                abort(403)
        return None

    @login_manager.unauthorized_handler
    def niet_ingelogd():
        if request.method != "GET" or request.headers.get("HX-Request"):
            abort(401)
        return redirect(url_for("auth.login", volgende=request.full_path))

    @app.after_request
    def security_headers(response):
        """Beveiligingsheaders op elk antwoord."""
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

        # Cache: pagina's en API-antwoorden nooit bewaren (ook niet door een proxy).
        # Scripts/CSS met versienummer (?v=...) mogen lang bewaard worden: bij een nieuwe
        # versie verandert het adres, dus dan haalt de browser (of proxy) het nieuwe bestand.
        if request.endpoint == "static":
            if request.args.get("v") == VERSIE:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(403)
    def verboden(_fout):
        from flask import render_template

        return render_template("fout.html", code=403, melding="Je hebt hier geen rechten voor."), 403

    @app.errorhandler(404)
    def niet_gevonden(_fout):
        from flask import render_template

        return render_template("fout.html", code=404, melding="Pagina niet gevonden."), 404


def _registreer_template_helpers(app: Flask) -> None:
    from .blueprints.hulp import externe_url
    from .services import instellingen
    from .services.kalender import DAGNAMEN, DAGNAMEN_KORT
    from .services.tijden import datum_nl
    from .services.urenberekening import formatteer_uren

    app.jinja_env.globals["externe_url"] = externe_url
    app.jinja_env.globals["dagnamen"] = DAGNAMEN
    app.jinja_env.globals["dagnamen_kort"] = DAGNAMEN_KORT
    app.jinja_env.filters["datum_nl"] = datum_nl
    app.jinja_env.filters["uren"] = formatteer_uren

    @app.context_processor
    def algemene_variabelen():
        """Variabelen die in elke template beschikbaar zijn."""
        try:
            teamnaam = instellingen.lees("teamnaam")
            voettekst = instellingen.lees("voettekst")
        except Exception:  # database nog niet aangemaakt (eerste start)
            teamnaam, voettekst = "Beveiligingsrooster", ""
        return {
            "teamnaam": teamnaam,
            "voettekst": voettekst,
            "versie": VERSIE,
            # Bestaat deze route? (zo verschijnen menu-items pas als de functie er is)
            "heeft_route": lambda endpoint: endpoint in app.view_functions,
        }
