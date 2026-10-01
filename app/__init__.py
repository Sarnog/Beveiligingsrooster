"""Beveiligingsrooster: Flask-app.

create_app() bouwt de app op: configuratie, database, login, blueprints en de
controles die bij elk verzoek draaien (setup-wizard, rechten, security-headers).
"""

import logging
import os
import time

from flask import Flask, abort, g, redirect, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager, migrate

VERSIE = "1.4.1"
verzoeklog = logging.getLogger("app.verzoek")

# Deze endpoints mogen ook zonder afgeronde setup bereikbaar zijn
SETUP_VRIJ = {"static", "algemeen.health", "auth.login", "auth.uitloggen",
              "pwa.manifest", "pwa.service_worker", "pwa.offline"}

# Deze endpoints zijn openbaar (geen login nodig); ze controleren zelf een geheim token
OPENBAAR = {"static", "algemeen.health", "pwa.manifest", "pwa.service_worker", "pwa.offline"}

# Schrijvende endpoints die een gewone gebruiker WEL mag gebruiken
GEBRUIKER_MAG_SCHRIJVEN = {
    "auth.login",
    "auth.uitloggen",
    "auth.wachtwoord_wijzigen",
    "account.tokens",
    "account.token_intrekken",
}

# API voor een app (alleen hier werken API-tokens; zie app/blueprints/api_v1.py)
API_PAD = "/api/v1/"
VEILIGE_METHODEN = ("GET", "HEAD", "OPTIONS")


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

    from . import debuglog

    debuglog.stel_in(app)

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
        account,
        algemeen,
        api_v1,
        auth,
        beheer,
        deel,
        ics,
        kalender,
        overzicht,
        pwa,
        rooster,
        setup,
        zoeken,
    )

    for module in (algemeen, auth, setup, beheer, kalender, rooster, overzicht, zoeken, deel, ics,
                   pwa, account, api_v1):
        app.register_blueprint(module.bp)
    # De API controleert CSRF zelf: wel bij een sessie, niet bij een API-token (zie controleer_toegang)
    csrf.exempt(api_v1.bp)


def _registreer_controles(app: Flask) -> None:
    from .models import Gebruiker
    from .services import instellingen

    @login_manager.user_loader
    def laad_gebruiker(sessiesleutel: str):
        """Gebruiker uit de sessie, alleen als die sessie nog geldig is (zie Gebruiker.get_id).

        Ongeldig na wachtwoord wijzigen/resetten, deactiveren of terugzetten van een
        back-up; ook het oude formaat (alleen het ID, vóór 1.3.0) is ongeldig.
        """
        delen = (sessiesleutel or "").split(":")
        if len(delen) != 3 or not delen[0].isascii() or not delen[0].isdecimal():
            return None
        gebruiker = db.session.get(Gebruiker, int(delen[0]))
        if gebruiker is None or not gebruiker.actief or gebruiker.get_id() != sessiesleutel:
            return None
        return gebruiker

    @login_manager.request_loader
    def laad_via_token(verzoek):
        """Inloggen met 'Authorization: Bearer <token>', alleen voor de API (nooit op pagina's)."""
        from .blueprints.auth import _client_ip
        from .services import api_tokens

        kop = verzoek.headers.get("Authorization", "")
        if not verzoek.path.startswith(API_PAD) or not kop.startswith("Bearer ") \
                or g.get("token_bezig"):  # het logboek vraagt zelf de gebruiker op: niet opnieuw
            return None
        g.token_bezig = True
        try:
            ip = _client_ip()
            token = kop[len("Bearer "):].strip()
            # Een geldig token werkt altijd (256 bits: niet te raden); alleen onbekende
            # tokens worden na te veel pogingen vanaf dit adres geweigerd
            if api_tokens.ip_geblokkeerd(ip) and not api_tokens.is_bekend(token):
                g.api_geblokkeerd = True
                _log_api_blokkade(ip)
                return None
            return api_tokens.gebruiker_bij_token(token, ip)
        finally:
            g.token_bezig = False

    @app.before_request
    def controleer_toegang():
        endpoint = request.endpoint or ""

        # 0. API: eigen controles (JSON, tokens). CSRF alleen bij een sessie: een
        #    Authorization-header stuurt een browser nooit vanzelf mee naar een andere site.
        if request.path.startswith(API_PAD) and instellingen.setup_voltooid():
            if request.method not in VEILIGE_METHODEN and app.config.get("WTF_CSRF_ENABLED", True) \
                    and not request.headers.get("Authorization", "").startswith("Bearer "):
                csrf.protect()
            return None

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

    def start_tijd():
        g.start_tijd = time.perf_counter()

    # Als eerste, zodat ook verzoeken die de toegangscontrole doorstuurt een duur krijgen
    app.before_request_funcs.setdefault(None, []).insert(0, start_tijd)

    @app.after_request
    def log_verzoek(response):
        """Debugregel per verzoek (pad met gemaskeerde tokens, nooit formulierinhoud)."""
        if request.endpoint != "static" and verzoeklog.isEnabledFor(logging.DEBUG):
            duur = (time.perf_counter() - g.get("start_tijd", time.perf_counter())) * 1000
            wie = current_user.gebruikersnaam if current_user.is_authenticated else "-"
            verzoeklog.debug("%s %s -> %s (%.0f ms, %s, %s)", request.method, request.path,
                             response.status_code, duur, wie, request.remote_addr)
        return response

    @login_manager.unauthorized_handler
    def niet_ingelogd():
        if request.method != "GET" or request.headers.get("HX-Request") or request.path.startswith(API_PAD):
            abort(401)
        return redirect(url_for("auth.login", volgende=request.full_path))

    @app.after_request
    def security_headers(response):
        """Beveiligingsheaders op elk antwoord."""
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # HSTS alleen als de app via HTTPS draait (Secure-cookies aan); anders sluit je
        # jezelf buiten op een LAN-adres zonder certificaat
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")

        # Cache: pagina's en API-antwoorden nooit bewaren (ook niet door een proxy).
        # Scripts/CSS met versienummer (?v=...) mogen lang bewaard worden: bij een nieuwe
        # versie verandert het adres, dus dan haalt de browser (of proxy) het nieuwe bestand.
        if request.endpoint in ("pwa.service_worker", "pwa.manifest"):
            pass  # eigen Cache-Control (no-cache)
        elif request.endpoint == "static":
            if request.args.get("v") == VERSIE:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-store"
        return response

    def api_fout(code: int, melding: str):
        from flask import jsonify

        return jsonify(fout=melding), code

    @app.errorhandler(400)
    def ongeldig(fout):
        if request.path.startswith(API_PAD):
            return api_fout(400, fout.description or "Ongeldig verzoek.")
        return fout

    @app.errorhandler(401)
    def niet_ingelogd_fout(fout):
        if request.path.startswith(API_PAD):
            antwoord = api_fout(401, "Niet ingelogd: stuur een geldig API-token mee "
                                     "(Authorization: Bearer ...).")
            antwoord[0].headers["WWW-Authenticate"] = 'Bearer realm="api"'
            return antwoord
        return fout

    @app.errorhandler(403)
    def verboden(_fout):
        from flask import render_template

        if request.path.startswith(API_PAD):
            return api_fout(403, "Je hebt hier geen rechten voor.")
        return render_template("fout.html", code=403, melding="Je hebt hier geen rechten voor."), 403

    @app.errorhandler(404)
    def niet_gevonden(_fout):
        from flask import render_template

        if request.path.startswith(API_PAD):
            return api_fout(404, "Niet gevonden.")
        return render_template("fout.html", code=404, melding="Pagina niet gevonden."), 404

    @app.errorhandler(405)
    def niet_toegestaan(fout):
        if request.path.startswith(API_PAD):
            return api_fout(405, "Deze API is alleen-lezen (GET).")
        return fout


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


def _log_api_blokkade(ip: str) -> None:
    """Eén logboekregel per blokkade van foute API-tokens (niet bij elk verzoek)."""
    from datetime import timedelta

    from .models import Logboek
    from .services import api_tokens, klok, logboek

    grens = klok.nu() - timedelta(minutes=api_tokens.BLOKKADE_MINUTEN)
    if Logboek.query.filter(Logboek.actie == "API geblokkeerd", Logboek.details == f"IP {ip}",
                            Logboek.tijdstempel >= grens).first() is None:
        logboek.log("API geblokkeerd", f"IP {ip}", gebruiker="", rol="")
        db.session.commit()
