"""Beveiligingsheaders en cookies (controle voor 1.3.0)."""

import re
from pathlib import Path

import pytest

from .conftest import login

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"


def test_geen_hsts_zonder_https(client, klaar):
    antwoord = client.get("/login")
    assert "Strict-Transport-Security" not in antwoord.headers


def test_hsts_alleen_met_secure_cookies(app, client, klaar):
    app.config["SESSION_COOKIE_SECURE"] = True
    antwoord = client.get("/login")
    assert antwoord.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_csp_zonder_unsafe_inline_voor_scripts(client, klaar):
    csp = client.get("/login").headers["Content-Security-Policy"]
    script = re.search(r"script-src ([^;]*)", csp).group(1)
    assert script.strip() == "'self'"
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp


def test_geen_inline_scripts_in_templates():
    """Met script-src 'self' werkt inline JavaScript niet; dus ook nergens gebruiken."""
    for pad in TEMPLATES.rglob("*.html"):
        tekst = pad.read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", tekst):
            assert "src=" in tag, f"inline <script> in {pad.name}"
        assert not re.search(r"\son(click|change|submit|load|input)=", tekst), f"on…= in {pad.name}"


@pytest.mark.parametrize("secure", [False, True])
def test_sessiecookie_httponly_samesite_en_secure(app, client, klaar, secure):
    app.config["SESSION_COOKIE_SECURE"] = secure
    antwoord = login(client, "beheerder")
    cookie = next(c for c in antwoord.headers.getlist("Set-Cookie") if c.startswith("session="))
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert ("Secure" in cookie) is secure


def test_cookie_secure_volgt_base_url(monkeypatch, tmp_path):
    from app.config import Config

    monkeypatch.setenv("DATA_MAP", str(tmp_path))
    monkeypatch.setenv("BASE_URL", "https://rooster.voorbeeld.nl")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    assert Config().SESSION_COOKIE_SECURE is True
    monkeypatch.setenv("COOKIE_SECURE", "0")
    assert Config().SESSION_COOKIE_SECURE is False


def test_inlogblokkade_per_gebruiker(client, klaar):
    for _ in range(5):
        login(client, "collega", "fout")
    antwoord = login(client, "collega")  # juist wachtwoord, maar geblokkeerd
    assert antwoord.status_code == 429 or "Te veel" in antwoord.get_data(as_text=True)
