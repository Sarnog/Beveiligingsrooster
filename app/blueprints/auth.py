"""Inloggen, uitloggen en wachtwoord wijzigen."""

import logging
from datetime import timedelta
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import Gebruiker, Logboek, LoginPoging
from ..services import klok, logboek
from ..services.wachtwoorden import (
    controleer_dummy,
    controleer_wachtwoord,
    hash_wachtwoord,
    moet_opnieuw_hashen,
    wachtwoord_fout,
)

bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

MAX_POGINGEN = 5  # mislukte pogingen ...
BLOKKADE_MINUTEN = 15  # ... per zoveel minuten, per gebruiker + IP
MAX_POGINGEN_PER_IP = MAX_POGINGEN * 4  # extra rem tegen veel namen proberen vanaf één IP
MAX_NAAM = 64  # langer kan een gebruikersnaam niet zijn (zie beheer/gebruikers.py)
_proxy_gewaarschuwd = False


def _client_ip() -> str:
    """IP-adres van de bezoeker. Achter een proxy alleen goed met PROXY_VERTROUWEN=1."""
    global _proxy_gewaarschuwd
    if request.headers.get("X-Forwarded-For") and not current_app.config.get("PROXY_VERTROUWEN") \
            and not _proxy_gewaarschuwd:
        _proxy_gewaarschuwd = True  # één keer per proces, anders loopt de log vol
        log.warning("Verzoek met X-Forwarded-For, maar PROXY_VERTROUWEN staat uit. Staat de app "
                    "achter een reverse proxy of tunnel? Zet dan PROXY_VERTROUWEN=1, anders lijken "
                    "alle bezoekers van hetzelfde IP-adres te komen (zie de README).")
    return (request.remote_addr or "onbekend")[:64]


def _mislukte_pogingen(gebruikersnaam: str, ip: str) -> tuple[int, int]:
    """Aantal mislukte pogingen in het venster: (deze gebruiker vanaf dit IP, alles vanaf dit IP)."""
    grens = klok.utc_nu() - timedelta(minutes=BLOKKADE_MINUTEN)
    basis = LoginPoging.query.filter(
        LoginPoging.gelukt.is_(False), LoginPoging.tijdstip >= grens
    )
    per_gebruiker = basis.filter(
        LoginPoging.gebruikersnaam == gebruikersnaam, LoginPoging.ip == ip
    ).count()
    per_ip = basis.filter(LoginPoging.ip == ip).count()
    return per_gebruiker, per_ip


def _is_geblokkeerd(gebruikersnaam: str, ip: str) -> bool:
    """True als deze gebruiker vanaf dit IP niet meer mag proberen.

    - Per gebruiker + IP: na MAX_POGINGEN fouten altijd geblokkeerd.
    - Per IP (veel verschillende namen): dan krijgt elke gebruiker nog precies één kans.
      Een collega die meteen het juiste wachtwoord geeft, komt er zo nog in, ook als
      iedereen via hetzelfde proxy-adres binnenkomt. Een aanvaller krijgt per naam
      hooguit één extra poging.
    """
    per_gebruiker, per_ip = _mislukte_pogingen(gebruikersnaam, ip)
    if per_gebruiker >= MAX_POGINGEN:
        return True
    return per_ip >= MAX_POGINGEN_PER_IP and per_gebruiker > 0


def _ip_geblokkeerd(ip: str) -> bool:
    return _mislukte_pogingen("", ip)[1] >= MAX_POGINGEN_PER_IP


def _blokkade_al_gelogd(gebruikersnaam: str, ip: str) -> bool:
    """Staat de blokkade van deze gebruiker + IP al in het logboek (binnen het venster)?"""
    grens = klok.nu() - timedelta(minutes=BLOKKADE_MINUTEN)
    return Logboek.query.filter(
        Logboek.actie == "Login geblokkeerd", Logboek.gebruiker == gebruikersnaam,
        Logboek.details == f"IP {ip}", Logboek.tijdstempel >= grens,
    ).first() is not None


def _veilige_volgende(volgende: str | None) -> str:
    """Alleen doorsturen naar een pagina binnen deze site."""
    if volgende:
        delen = urlparse(volgende)
        if not delen.scheme and not delen.netloc and volgende.startswith("/"):
            return volgende
    return url_for("algemeen.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("algemeen.index"))

    if request.method == "POST":
        ingevuld = request.form.get("gebruikersnaam", "").strip().lower()
        # Afkappen vóór het opslaan of opzoeken; een langere naam kan niet bestaan
        gebruikersnaam = ingevuld[:MAX_NAAM]
        te_lang = len(ingevuld) > MAX_NAAM
        wachtwoord = request.form.get("wachtwoord", "")
        ip = _client_ip()

        if _is_geblokkeerd(gebruikersnaam, ip):
            log.debug("Login geblokkeerd: %r vanaf %s", gebruikersnaam, ip)
            return _geblokkeerd(gebruikersnaam, ip)

        gebruiker = None if te_lang else \
            Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).first()
        if gebruiker is None:
            klopt = controleer_dummy(wachtwoord)  # zelfde rekentijd: niets verraden
        else:
            klopt = gebruiker.actief and controleer_wachtwoord(gebruiker.wachtwoord_hash, wachtwoord)
        db.session.add(LoginPoging(gebruikersnaam=gebruikersnaam, ip=ip, gelukt=klopt))

        if not klopt:
            # Nooit het wachtwoord loggen, alleen de reden
            reden = "onbekende gebruiker" if gebruiker is None else (
                "account niet actief" if not gebruiker.actief else "verkeerd wachtwoord")
            log.debug("Login mislukt: %r vanaf %s (%s)", gebruikersnaam, ip, reden)
            logboek.log("Login mislukt", f"IP {ip}", gebruiker=gebruikersnaam, rol="")
            db.session.commit()
            if _ip_geblokkeerd(ip):
                return _geblokkeerd(gebruikersnaam, ip)
            flash("Onjuiste gebruikersnaam of wachtwoord.", "fout")
            return render_template("auth/login.html"), 401

        # Gelukt: hash eventueel vernieuwen, tijdstip bijhouden, loggen
        log.debug("Login gelukt: %r (%s) vanaf %s", gebruiker.gebruikersnaam, gebruiker.rol, ip)
        if moet_opnieuw_hashen(gebruiker.wachtwoord_hash):
            gebruiker.wachtwoord_hash = hash_wachtwoord(wachtwoord)
        gebruiker.laatst_ingelogd = klok.nu()
        logboek.log("Login", f"IP {ip}", gebruiker=gebruiker.gebruikersnaam, rol=gebruiker.rol)
        db.session.commit()

        session.permanent = True  # sessieduur volgens SESSIE_UREN
        login_user(gebruiker)
        return redirect(_veilige_volgende(request.args.get("volgende")))

    return render_template("auth/login.html")


def _geblokkeerd(gebruikersnaam: str, ip: str):
    """Antwoord bij een blokkade. Eén logboekregel per blokkade, niet bij elke poging."""
    if not _blokkade_al_gelogd(gebruikersnaam, ip):
        logboek.log("Login geblokkeerd", f"IP {ip}", gebruiker=gebruikersnaam, rol="")
        db.session.commit()
    flash(f"Te veel mislukte pogingen. Probeer het over {BLOKKADE_MINUTEN} minuten opnieuw.", "fout")
    return render_template("auth/login.html"), 429


@bp.route("/uitloggen", methods=["POST"])
def uitloggen():
    if current_user.is_authenticated:
        logboek.log("Uitloggen")
        db.session.commit()
    logout_user()
    session.clear()
    flash("Je bent uitgelogd.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account/wachtwoord", methods=["GET", "POST"])
@login_required
def wachtwoord_wijzigen():
    if request.method == "POST":
        huidig = request.form.get("huidig", "")
        nieuw = request.form.get("nieuw", "")
        herhaling = request.form.get("herhaling", "")

        if not controleer_wachtwoord(current_user.wachtwoord_hash, huidig):
            flash("Het huidige wachtwoord klopt niet.", "fout")
        elif fout := wachtwoord_fout(nieuw, herhaling):
            flash(fout, "fout")
        elif nieuw == huidig:
            flash("Kies een ander wachtwoord dan het huidige.", "fout")
        else:
            gebruiker = current_user._get_current_object()
            gebruiker.wachtwoord_hash = hash_wachtwoord(nieuw)
            gebruiker.moet_wachtwoord_wijzigen = False
            gebruiker.maak_sessies_ongeldig()  # andere sessies (andere apparaten) uitloggen
            logboek.log("Wachtwoord gewijzigd", "Eigen wachtwoord")
            db.session.commit()
            login_user(gebruiker)  # deze sessie blijft geldig
            flash("Je wachtwoord is gewijzigd.", "succes")
            return redirect(url_for("algemeen.index"))
    return render_template("auth/wachtwoord.html")
