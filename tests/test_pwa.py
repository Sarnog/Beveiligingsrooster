"""Installeerbaar als app (PWA): manifest, iconen, iOS-metatags, service worker en offline-pagina."""

import json
import struct

from app import VERSIE


def _png_maat(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifest(client, klaar):
    antwoord = client.get("/manifest.webmanifest")  # openbaar: de browser stuurt geen cookies mee
    assert antwoord.status_code == 200
    assert antwoord.mimetype == "application/manifest+json"
    manifest = json.loads(antwoord.data)
    assert manifest["name"] and manifest["short_name"]
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/" and manifest["scope"] == "/"
    assert manifest["theme_color"] == "#16325c" and manifest["lang"] == "nl"
    maten = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= maten
    for icoon in manifest["icons"]:
        assert f"v={VERSIE}" in icoon["src"]
        data = client.get(icoon["src"]).data
        breedte, hoogte = _png_maat(data)
        assert f"{breedte}x{hoogte}" == icoon["sizes"]


def test_manifest_gebruikt_teamnaam(client, klaar):
    from app.extensions import db
    from app.services import instellingen

    instellingen.schrijf("teamnaam", "Team Noord")
    db.session.commit()
    manifest = json.loads(client.get("/manifest.webmanifest").data)
    assert manifest["name"] == "Rooster Team Noord"


def test_metatags_voor_app_en_ios(client, klaar):
    pagina = client.get("/login").get_data(as_text=True)
    assert '<link rel="manifest" href="/manifest.webmanifest">' in pagina
    assert '<meta name="theme-color" content="#16325c">' in pagina
    assert '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png?v=' in pagina
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in pagina
    assert '<meta name="mobile-web-app-capable" content="yes">' in pagina
    assert 'name="apple-mobile-web-app-title"' in pagina
    assert _png_maat(client.get(f"/static/icons/apple-touch-icon.png?v={VERSIE}").data) == (180, 180)


def test_service_worker_headers(client, klaar):
    antwoord = client.get("/sw.js")  # openbaar en zonder setup
    assert antwoord.status_code == 200
    assert antwoord.mimetype == "text/javascript"
    assert antwoord.headers["Cache-Control"] == "no-cache"
    assert antwoord.headers.get("Service-Worker-Allowed", "/") == "/"


def test_service_worker_inhoud(client, klaar):
    script = client.get("/sw.js").get_data(as_text=True)
    # Cache-naam met de versie; oude caches opruimen bij activate
    assert f'var CACHE = "rooster-{VERSIE}";' in script
    assert 'addEventListener("activate"' in script and "caches.delete" in script
    # Alleen statische bestanden met ?v=<VERSIE> en de offline-pagina
    assert f'"/offline?v={VERSIE}"' in script
    assert 'url.pathname.indexOf("/static/") === 0' in script
    assert 'url.searchParams.get("v") === VERSIE' in script
    # Nooit HTML-pagina's of /api/-antwoorden cachen
    assert "cache.put" not in script.split("// Statische bestanden")[0]
    assert '"/api/"' in script


def test_offline_pagina(client, app):
    antwoord = client.get(f"/offline?v={VERSIE}")  # ook vóór de setup bereikbaar
    assert antwoord.status_code == 200
    assert "Je bent offline" in antwoord.get_data(as_text=True)


def test_service_worker_wordt_geregistreerd():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "app" / "static" / "js" / "app.js").read_text()
    assert 'navigator.serviceWorker.register("/sw.js"' in script


def test_csp_staat_service_worker_en_manifest_toe(client, klaar):
    csp = client.get("/login").headers["Content-Security-Policy"]
    # default-src 'self' geldt ook voor worker-src en manifest-src: geen aanpassing nodig
    assert "default-src 'self'" in csp and "worker-src" not in csp
