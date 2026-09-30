"""Beheerschermen (alleen voor de beheerder).

Alle routes staan onder /beheer en zijn beveiligd met @beheerder_vereist.
Daarnaast blokkeert de algemene controle in app/__init__.py elke schrijvende
actie van een gewone gebruiker (dubbele zekerheid).
"""

from flask import Blueprint, render_template

from ..hulp import beheerder_vereist

bp = Blueprint("beheer", __name__, url_prefix="/beheer")


@bp.route("/")
@beheerder_vereist
def index():
    return render_template("beheer/index.html")


# Routes uit de losse modules registreren (import na het aanmaken van bp)
from . import dienstcodes, gebruikers, instellingen, kalender, medewerkers  # noqa: E402,F401
