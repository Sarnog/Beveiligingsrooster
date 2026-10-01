"""Logboek bekijken (alleen beheerder): nieuwste eerst, met filters en pagina's."""

from datetime import timedelta

from flask import render_template, request

from ...extensions import db
from ...models import Logboek
from ...services.tijden import parse_datum
from ..hulp import begrensd_getal, beheerder_vereist
from . import bp

PER_PAGINA = 50


@bp.route("/logboek")
@beheerder_vereist
def logboek():
    query = Logboek.query
    gebruiker = request.args.get("gebruiker", "").strip()
    actie = request.args.get("actie", "").strip()
    van = parse_datum(request.args.get("van"))
    tot = parse_datum(request.args.get("tot"))
    if gebruiker:
        query = query.filter(Logboek.gebruiker == gebruiker)
    if actie:
        query = query.filter(Logboek.actie == actie)
    if van:
        query = query.filter(Logboek.tijdstempel >= van)
    if tot:
        query = query.filter(Logboek.tijdstempel < tot + timedelta(days=1))
    pagina = query.order_by(Logboek.tijdstempel.desc(), Logboek.id.desc()).paginate(
        page=request.args.get("pagina", 1, type=begrensd_getal) or 1, per_page=PER_PAGINA, error_out=False)
    gebruikers = [g for (g,) in db.session.query(Logboek.gebruiker).distinct().order_by(Logboek.gebruiker)]
    acties = [a for (a,) in db.session.query(Logboek.actie).distinct().order_by(Logboek.actie)]
    return render_template("beheer/logboek.html", pagina=pagina, gebruikers=gebruikers,
                           acties=acties, args=request.args)
