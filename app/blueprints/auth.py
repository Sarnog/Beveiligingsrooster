"""Inloggen, uitloggen en wachtwoord wijzigen."""

from datetime import timedelta
from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import Gebruiker, LoginPoging
from ..services import klok, logboek
from ..services.wachtwoorden import (
    controleer_wachtwoord,
    hash_wachtwoord,
    moet_opnieuw_hashen,
    wachtwoord_fout,
)

bp = Blueprint("auth", __name__)

MAX_POGINGEN = 5  # mislukte pogingen ...
BLOKKADE_MINUTEN = 15  # ... per zoveel minuten, per gebruiker + IP


def _client_ip() -> str:
    return request.remote_addr or "onbekend"


def _is_geblokkeerd(gebruikersnaam: str, ip: str) -> bool:
    """True als er te veel mislukte pogingen waren (per gebruiker + IP, en per IP)."""
    grens = klok.nu() - timedelta(minutes=BLOKKADE_MINUTEN)
    basis = LoginPoging.query.filter(
        LoginPoging.gelukt.is_(False), LoginPoging.tijdstip >= grens
    )
    per_gebruiker = basis.filter(
        LoginPoging.gebruikersnaam == gebruikersnaam, LoginPoging.ip == ip
    ).count()
    # Extra rem tegen het uitproberen van veel gebruikersnamen vanaf één IP
    per_ip = basis.filter(LoginPoging.ip == ip).count()
    return per_gebruiker >= MAX_POGINGEN or per_ip >= MAX_POGINGEN * 4


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
        gebruikersnaam = request.form.get("gebruikersnaam", "").strip().lower()
        wachtwoord = request.form.get("wachtwoord", "")
        ip = _client_ip()

        if _is_geblokkeerd(gebruikersnaam, ip):
            logboek.log("Login geblokkeerd", f"IP {ip}", gebruiker=gebruikersnaam, rol="")
            db.session.commit()
            flash(
                f"Te veel mislukte pogingen. Probeer het over {BLOKKADE_MINUTEN} minuten opnieuw.",
                "fout",
            )
            return render_template("auth/login.html"), 429

        gebruiker = Gebruiker.query.filter_by(gebruikersnaam=gebruikersnaam).first()
        klopt = (
            gebruiker is not None
            and gebruiker.actief
            and controleer_wachtwoord(gebruiker.wachtwoord_hash, wachtwoord)
        )
        db.session.add(LoginPoging(gebruikersnaam=gebruikersnaam, ip=ip, gelukt=klopt))

        if not klopt:
            logboek.log("Login mislukt", f"IP {ip}", gebruiker=gebruikersnaam, rol="")
            db.session.commit()
            flash("Onjuiste gebruikersnaam of wachtwoord.", "fout")
            return render_template("auth/login.html"), 401

        # Gelukt: hash eventueel vernieuwen, tijdstip bijhouden, loggen
        if moet_opnieuw_hashen(gebruiker.wachtwoord_hash):
            gebruiker.wachtwoord_hash = hash_wachtwoord(wachtwoord)
        gebruiker.laatst_ingelogd = klok.nu()
        logboek.log("Login", f"IP {ip}", gebruiker=gebruiker.gebruikersnaam, rol=gebruiker.rol)
        db.session.commit()

        session.permanent = True  # sessieduur volgens SESSIE_UREN
        login_user(gebruiker)
        return redirect(_veilige_volgende(request.args.get("volgende")))

    return render_template("auth/login.html")


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
            current_user.wachtwoord_hash = hash_wachtwoord(nieuw)
            current_user.moet_wachtwoord_wijzigen = False
            logboek.log("Wachtwoord gewijzigd", "Eigen wachtwoord")
            db.session.commit()
            flash("Je wachtwoord is gewijzigd.", "succes")
            return redirect(url_for("algemeen.index"))
    return render_template("auth/wachtwoord.html")
