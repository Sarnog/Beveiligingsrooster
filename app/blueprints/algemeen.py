"""Algemene routes: startpagina en /health."""

from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import login_required
from sqlalchemy import text

from ..extensions import db

bp = Blueprint("algemeen", __name__)


@bp.route("/")
@login_required
def index():
    """Startpagina. Zodra de kalender bestaat (fase 2) sturen we daarheen door."""
    if "kalender.jaar" in _endpoints():
        return redirect(url_for("kalender.jaar"))
    return render_template("index.html")


def _endpoints() -> set[str]:
    from flask import current_app

    return set(current_app.view_functions.keys())


@bp.route("/health")
def health():
    """Voor monitoring en de Docker-healthcheck: controleert ook de database."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok")
    except Exception:  # noqa: BLE001 - elke databasefout is 'niet gezond'
        return jsonify(status="fout"), 503
