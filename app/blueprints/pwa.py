"""Installeerbaar als app (PWA): manifest, service worker en offline-pagina.

Alle drie openbaar: de browser haalt ze op zonder in te loggen (het manifest zelfs
zonder cookies). Er staat geen roosterdata in.
"""

from flask import Blueprint, jsonify, make_response, render_template, url_for

from ..services import instellingen

bp = Blueprint("pwa", __name__)

THEMAKLEUR = "#16325c"  # kleur van de bovenbalk


@bp.route("/manifest.webmanifest")
def manifest():
    from .. import VERSIE

    try:
        teamnaam = instellingen.lees("teamnaam")
    except Exception:  # database nog niet aangemaakt (eerste start)
        teamnaam = ""

    def icoon(bestand: str, maat: int, doel: str = "any") -> dict:
        return {"src": url_for("static", filename=f"icons/{bestand}", v=VERSIE),
                "sizes": f"{maat}x{maat}", "type": "image/png", "purpose": doel}

    antwoord = jsonify({
        "name": f"Rooster {teamnaam}".strip() if teamnaam else "Beveiligingsrooster",
        "short_name": "Rooster",
        "description": "Jaarrooster en urenregistratie van het team",
        "lang": "nl",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f6f9",
        "theme_color": THEMAKLEUR,
        "icons": [icoon("icoon-192.png", 192), icoon("icoon-512.png", 512),
                  icoon("icoon-maskable-512.png", 512, "maskable")],
    })
    antwoord.mimetype = "application/manifest+json"
    antwoord.headers["Cache-Control"] = "no-cache"
    return antwoord


@bp.route("/sw.js")
def service_worker():
    """Service worker vanaf de hoofdmap (scope /). Altijd eerst bij de server navragen
    (no-cache), zodat een nieuwe versie van de app direct een nieuwe worker krijgt."""
    from .. import VERSIE

    statisch = [url_for("static", filename=f, v=VERSIE) for f in (
        "css/style.css", "js/app.js", "favicon.svg", "icons/icoon-192.png")]
    antwoord = make_response(render_template("pwa/sw.js", versie=VERSIE, statisch=statisch,
                                             offline=url_for("pwa.offline", v=VERSIE)))
    antwoord.mimetype = "text/javascript"
    antwoord.headers["Cache-Control"] = "no-cache"
    antwoord.headers["Service-Worker-Allowed"] = "/"
    return antwoord


@bp.route("/offline")
def offline():
    """Getoond door de service worker als er geen verbinding is. Zonder persoonlijke gegevens."""
    # teamnaam komt uit de contextprocessor (met 'Beveiligingsrooster' als terugval)
    return render_template("pwa/offline.html")
