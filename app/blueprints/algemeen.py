"""Algemene routes: startpagina en /health."""

from flask import Blueprint, jsonify, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("algemeen", __name__)


@bp.route("/")
@login_required
def index():
    """Startpagina: 'Mijn rooster' voor een gekoppelde collega, anders de kalender."""
    if not current_user.is_beheerder and current_user.medewerker_id:
        return redirect(url_for("rooster.mijn"))
    return redirect(url_for("kalender.jaar"))


@bp.route("/health")
def health():
    """Voor monitoring en de Docker-healthcheck: controleert ook de database."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok")
    except Exception:  # elke databasefout is 'niet gezond'
        return jsonify(status="fout"), 503
