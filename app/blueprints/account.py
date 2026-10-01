"""Account: persoonlijke API-tokens voor een app (aanmaken en intrekken).

Elke gebruiker beheert alleen zijn eigen tokens. Een nieuw token wordt één keer
getoond, direct in het antwoord (niet via een flash-melding in de sessiecookie).
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import ApiToken
from ..services import api_tokens, klok

bp = Blueprint("account", __name__, url_prefix="/account")


def _mijn_tokens() -> list[ApiToken]:
    return (ApiToken.query.filter_by(gebruiker_id=current_user.id)
            .order_by(ApiToken.aangemaakt_op.desc()).all())


@bp.route("/tokens", methods=["GET", "POST"])
@login_required
def tokens():
    nieuw_token = None
    status = 200
    if request.method == "POST":
        naam = request.form.get("naam", "").strip()
        dagen = request.form.get("dagen", type=int)
        if not naam or len(naam) > 60:
            flash("Geef het token een naam (hooguit 60 tekens), bijvoorbeeld 'Telefoon'.", "fout")
            status = 400
        elif dagen not in api_tokens.GELDIGHEID_DAGEN:
            flash("Kies een geldige termijn.", "fout")
            status = 400
        else:
            nieuw_token, _record = api_tokens.maak(current_user._get_current_object(), naam, dagen)
            db.session.commit()
    return render_template("account/tokens.html", tokens=_mijn_tokens(), nieuw_token=nieuw_token,
                           termijnen=api_tokens.GELDIGHEID_DAGEN, nu=klok.utc_nu(),
                           is_geldig=api_tokens.is_geldig), status


@bp.route("/tokens/<int:tid>/intrekken", methods=["POST"])
@login_required
def token_intrekken(tid: int):
    record = db.session.get(ApiToken, tid)
    if record is None or record.gebruiker_id != current_user.id:
        abort(404)
    api_tokens.trek_in(record)
    db.session.commit()
    flash(f"Token '{record.naam}' is ingetrokken; het werkt niet meer.", "succes")
    return redirect(url_for("account.tokens"))
