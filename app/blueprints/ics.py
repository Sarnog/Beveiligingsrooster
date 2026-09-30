"""Openbare ICS-feed per medewerker: /ics/<geheim-token>.ics (geen login nodig)."""

import hmac

from flask import Blueprint, Response, abort

from ..models import Medewerker
from ..services.ics import maak_feed

bp = Blueprint("ics", __name__, url_prefix="/ics")


@bp.route("/<token>.ics")
def feed(token: str):
    if len(token) < 20:
        abort(404)
    medewerker = Medewerker.query.filter_by(ics_token=token).first()
    if medewerker is None or not hmac.compare_digest(medewerker.ics_token.encode(), token.encode()):
        abort(404)
    return Response(maak_feed(medewerker), mimetype="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": "inline; filename=rooster.ics",
                             "Cache-Control": "no-store"})
