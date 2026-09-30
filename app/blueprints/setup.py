"""Setup-wizard voor de eerste start.

Stap 0: setup-code invoeren (uit de installatie-output of het log)
Stap 1: beheerdersaccount
Stap 2: algemene instellingen
Stap 3: dienstcodes (leeg of voorbeeldpakket)
Stap 4: medewerkers (mag ook later)
Stap 5: Google Agenda (mag ook later) -> afronden
"""


from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user

from ..extensions import db
from ..models import ROL_BEHEERDER, Contracturen, Gebruiker, Medewerker
from ..services import instellingen, klok, logboek, setup_code
from ..services.medewerkers import uniek_voorstel
from ..services.voorbeeldpakket import laad_voorbeeldpakket
from ..services.wachtwoorden import hash_wachtwoord, wachtwoord_fout
from .hulp import getal

bp = Blueprint("setup", __name__, url_prefix="/setup")

LAATSTE_STAP = 5


@bp.before_request
def alleen_tijdens_setup():
    """Na afronding is /setup niet meer bereikbaar."""
    if instellingen.setup_voltooid():
        abort(404)


def _beheerder_bestaat() -> bool:
    return Gebruiker.query.filter_by(rol=ROL_BEHEERDER).first() is not None


@bp.route("/", methods=["GET", "POST"])
def start():
    """Stap 0: vraag de setup-code."""
    setup_code.haal_of_maak_code()  # zorgt dat er een code is (en toont die in het log)

    if request.method == "POST":
        if setup_code.controleer_code(request.form.get("code", "")):
            session["setup_code_ok"] = True
            return redirect(url_for("setup.stap", nummer=1))
        flash("De setup-code klopt niet.", "fout")
        return render_template("setup/code.html"), 400

    if session.get("setup_code_ok"):
        return redirect(url_for("setup.stap", nummer=1))
    return render_template("setup/code.html")


@bp.route("/stap/<int:nummer>", methods=["GET", "POST"])
def stap(nummer: int):
    if not session.get("setup_code_ok"):
        return redirect(url_for("setup.start"))
    if nummer < 1 or nummer > LAATSTE_STAP:
        abort(404)

    # Stap 1 alleen zolang er nog geen beheerder is
    if nummer == 1 and _beheerder_bestaat():
        if current_user.is_authenticated and current_user.is_beheerder:
            return redirect(url_for("setup.stap", nummer=2))
        flash("Er is al een beheerder. Log in om de setup af te maken.", "info")
        return redirect(url_for("auth.login", volgende=url_for("setup.stap", nummer=2)))

    # Stap 2 t/m 5: alleen als ingelogde beheerder
    if nummer > 1 and not (current_user.is_authenticated and current_user.is_beheerder):
        return redirect(url_for("setup.stap", nummer=1))

    functies = {1: _stap_beheerder, 2: _stap_algemeen, 3: _stap_dienstcodes,
                4: _stap_medewerkers, 5: _stap_agenda}
    return functies[nummer]()


def _volgende(nummer: int):
    return redirect(url_for("setup.stap", nummer=nummer + 1))


def _stap_beheerder():
    if request.method == "POST":
        gebruikersnaam = request.form.get("gebruikersnaam", "").strip().lower()
        weergavenaam = request.form.get("weergavenaam", "").strip()
        wachtwoord = request.form.get("wachtwoord", "")
        herhaling = request.form.get("herhaling", "")

        fout = None
        if not gebruikersnaam or not weergavenaam:
            fout = "Vul een gebruikersnaam en weergavenaam in."
        else:
            fout = wachtwoord_fout(wachtwoord, herhaling)
        if fout:
            flash(fout, "fout")
            return render_template("setup/stap1.html", stap=1), 400

        beheerder = Gebruiker(
            gebruikersnaam=gebruikersnaam,
            weergavenaam=weergavenaam,
            wachtwoord_hash=hash_wachtwoord(wachtwoord),
            rol=ROL_BEHEERDER,
        )
        db.session.add(beheerder)
        logboek.log("Account aangemaakt", "Eerste beheerder (setup)",
                    gebruiker=gebruikersnaam, rol=ROL_BEHEERDER, nieuw=gebruikersnaam)
        db.session.commit()
        login_user(beheerder)
        return _volgende(1)
    return render_template("setup/stap1.html", stap=1)


def _stap_algemeen():
    if request.method == "POST":
        formulier = request.form
        za = getal(formulier.get("toeslag_zaterdag"))
        zo = getal(formulier.get("toeslag_zondag"))
        dagen = formulier.get("logboek_dagen", "31").strip()
        uren = formulier.get("logboek_uren", "0").strip()
        jaar = formulier.get("eerste_jaar", "").strip()
        if za is None or zo is None or not dagen.isdigit() or not uren.isdigit() \
                or not jaar.isdigit() or not (0 <= int(uren) <= 23):
            flash("Controleer de ingevulde waarden.", "fout")
            return render_template("setup/stap2.html", stap=2, w=formulier), 400
        instellingen.schrijf("teamnaam", formulier.get("teamnaam", "").strip() or "Beveiligingsrooster")
        instellingen.schrijf("tijdzone", formulier.get("tijdzone", "Europe/Amsterdam").strip())
        instellingen.schrijf("eerste_jaar", jaar)
        instellingen.schrijf("toeslag_zaterdag", za)
        instellingen.schrijf("toeslag_zondag", zo)
        instellingen.schrijf("logboek_dagen", dagen)
        instellingen.schrijf("logboek_uren", uren)
        logboek.log("Instellingen gewijzigd", "Setup: algemene instellingen")
        db.session.commit()
        return _volgende(2)
    waarden = {s: instellingen.lees(s) for s in instellingen.STANDAARD}
    waarden["eerste_jaar"] = waarden["eerste_jaar"] or str(klok.vandaag().year)
    return render_template("setup/stap2.html", stap=2, w=waarden)


def _stap_dienstcodes():
    if request.method == "POST":
        if request.form.get("keuze") == "voorbeeld":
            codes, regels = laad_voorbeeldpakket()
            logboek.log("Dienstcodes", f"Voorbeeldpakket geladen: {codes} codes, {regels} kleurregels")
            db.session.commit()
            flash(f"Voorbeeldpakket geladen ({codes} dienstcodes).", "succes")
        return _volgende(3)
    return render_template("setup/stap3.html", stap=3)


def _stap_medewerkers():
    """Medewerkers invoeren: één per regel, 'Naam' of 'Naam;contracturen'."""
    if request.method == "POST":
        if request.form.get("overslaan"):
            return _volgende(4)
        jaar = instellingen.lees_int("eerste_jaar", klok.vandaag().year)
        regels = [r.strip() for r in request.form.get("medewerkers", "").splitlines() if r.strip()]
        volgorde = Medewerker.query.count()
        toegevoegd = 0
        for regel in regels:
            naam, _, uren_tekst = regel.partition(";")
            naam = naam.strip()
            if not naam:
                continue
            volgorde += 1
            medewerker = Medewerker(naam=naam, initialen=uniek_voorstel(naam) or f"M{volgorde}",
                                    volgorde=volgorde)
            db.session.add(medewerker)
            db.session.flush()  # zodat de volgende uniek_voorstel deze ook ziet
            uren = getal(uren_tekst)
            if uren is not None:
                db.session.add(Contracturen(medewerker_id=medewerker.id, jaar=jaar, uren=uren))
            logboek.log("Medewerker toegevoegd", "Setup", medewerker=naam, nieuw=medewerker.initialen)
            toegevoegd += 1
        db.session.commit()
        if toegevoegd:
            flash(f"{toegevoegd} medewerker(s) toegevoegd.", "succes")
        return _volgende(4)
    return render_template("setup/stap4.html", stap=4)


def _stap_agenda():
    """Laatste stap: Google Agenda kan later via Beheer. Hier ronden we af."""
    if request.method == "POST":
        instellingen.schrijf("setup_voltooid", "1")
        logboek.log("Setup afgerond")
        db.session.commit()
        setup_code.verwijder_code()  # code is vanaf nu ongeldig
        session.pop("setup_code_ok", None)
        flash("De setup is afgerond. Welkom!", "succes")
        return redirect(url_for("algemeen.index"))
    return render_template("setup/stap5.html", stap=5)
