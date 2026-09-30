"""Alleen-lezen deellink: het rooster bekijken zonder account (via een geheim token).

Staat standaard uit (Beheer -> Instellingen). Alleen GET-routes; er kan hier niets
gewijzigd worden. De urenoverzichten per medewerker worden via de deellink niet getoond.
"""

import hmac

from flask import Blueprint, abort, render_template, request

from ..models import Dienstcode
from ..services import instellingen, klok
from ..services.kalender import week_van
from ..services.overzichten import jaarkalender, roostervrije_dagen, weken_lijst
from ..services.weekrooster import week_gegevens
from .rooster import geldige_week, navigatie

bp = Blueprint("deel", __name__, url_prefix="/deel")


def _controleer(token: str) -> None:
    """404 als de deellink uit staat of het token niet klopt (niets verraden)."""
    juist = instellingen.lees("deellink_token")
    if not instellingen.lees_bool("deellink_actief") or not juist \
            or not hmac.compare_digest(token.encode(), juist.encode()):
        abort(404)


@bp.route("/<token>/")
def kalender(token: str):
    _controleer(token)
    jaar = min(max(request.args.get("jaar", type=int) or klok.vandaag().year, 1950), 2150)
    return render_template(
        "kalender/jaar.html", jaar=jaar, maanden=jaarkalender(jaar), weken=weken_lijst(jaar),
        overzicht=None, feestdagen=roostervrije_dagen(jaar),
        laatst_bijgewerkt=instellingen.lees("laatst_bijgewerkt"),
        huidige_week=week_van(klok.vandaag()), deel_token=token,
    )


@bp.route("/<token>/week/<int:jaar>/<int:week>")
def week(token: str, jaar: int, week: int):
    _controleer(token)
    if not geldige_week(jaar, week):
        abort(404)
    return render_template(
        "rooster/week.html", **week_gegevens(jaar, week),
        codes=Dienstcode.query.filter_by(actief=True).order_by(Dienstcode.nummer).all(),
        bewerken=False, markeer_dag=request.args.get("dag", ""),
        blanco=instellingen.blanco_code(), deel_token=token, **navigatie(jaar, week),
    )
