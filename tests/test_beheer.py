"""Beheerschermen: medewerkers, dienstcodes, vakanties, feestdagen, instellingen."""

import os
from datetime import date, timedelta

from app.extensions import db
from app.models import Dienst, Dienstcode, Feestdag, Logboek, Medewerker, Vakantie
from app.services import instellingen
from app.services.rooster import bereken_dienst
from app.services.voorbeeldpakket import laad_voorbeeldpakket


def test_medewerker_toevoegen_met_initialen_en_contracturen(als_beheerder):
    antwoord = als_beheerder.post("/beheer/medewerkers/nieuw", data={
        "naam": "Jan Jansen", "initialen": "", "cu_jaar_nieuw": "2026", "cu_uren_nieuw": "1659"})
    assert antwoord.status_code == 302
    medewerker = Medewerker.query.one()
    assert medewerker.initialen == "JJA"
    assert medewerker.contracturen_voor(2026) == 1659
    assert medewerker.contracturen_voor(2027) == 1659  # geldt door tot een nieuw jaar
    assert medewerker.contracturen_voor(2025) is None


def test_initialen_moeten_uniek_zijn(als_beheerder):
    als_beheerder.post("/beheer/medewerkers/nieuw", data={"naam": "Jan Jansen", "initialen": "JJA"})
    antwoord = als_beheerder.post("/beheer/medewerkers/nieuw",
                                  data={"naam": "Joop Janssen", "initialen": "JJA"})
    assert antwoord.status_code == 400
    assert Medewerker.query.count() == 1
    # Voorstel krijgt een volgnummer
    assert als_beheerder.get("/beheer/medewerkers/initialen?naam=Joop+Janssen").json["initialen"] == "JJA2"


def test_naamwijziging_wordt_gelogd(als_beheerder):
    als_beheerder.post("/beheer/medewerkers/nieuw", data={"naam": "Medewerker A", "initialen": "TSA"})
    medewerker = Medewerker.query.one()
    als_beheerder.post(f"/beheer/medewerkers/{medewerker.id}",
                       data={"naam": "Medewerker B", "initialen": "TSA"})
    regel = Logboek.query.filter_by(actie="Medewerker gewijzigd", veld="naam").one()
    assert (regel.oude_waarde, regel.nieuwe_waarde) == ("Medewerker A", "Medewerker B")


def test_volgorde_wijzigen(als_beheerder):
    for naam, init in [("Medewerker A", "TSA"), ("Medewerker B", "TSB")]:
        als_beheerder.post("/beheer/medewerkers/nieuw", data={"naam": naam, "initialen": init})
    b = Medewerker.query.filter_by(initialen="TSB").one()
    als_beheerder.post(f"/beheer/medewerkers/{b.id}/verplaats", data={"richting": "omhoog"})
    volgorde = [m.initialen for m in Medewerker.query.order_by(Medewerker.volgorde).all()]
    assert volgorde == ["TSB", "TSA"]


def test_verwijderen_met_diensten_vraagt_bevestiging(als_beheerder):
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.flush()
    db.session.add(Dienst(medewerker_id=medewerker.id, datum=date(2026, 3, 2)))
    db.session.commit()
    antwoord = als_beheerder.post(f"/beheer/medewerkers/{medewerker.id}/verwijder", data={})
    assert antwoord.status_code == 400 and Medewerker.query.count() == 1
    als_beheerder.post(f"/beheer/medewerkers/{medewerker.id}/verwijder", data={"bevestig": "1"})
    assert Medewerker.query.count() == 0 and Dienst.query.count() == 0


def test_archiveren(als_beheerder):
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.commit()
    als_beheerder.post(f"/beheer/medewerkers/{medewerker.id}/archiveer", data={"vanaf": "2026-06-01"})
    medewerker = db.session.get(Medewerker, medewerker.id)
    assert medewerker.gearchiveerd_vanaf == date(2026, 6, 1)
    assert medewerker.is_zichtbaar_op(date(2026, 5, 31))
    assert not medewerker.is_zichtbaar_op(date(2026, 6, 1))


def test_dienstcode_toevoegen_en_tijden_normaliseren(als_beheerder):
    als_beheerder.post("/beheer/dienstcodes/nieuw", data={
        "nummer": "4", "omschrijving": "VW Vroeg", "std_begin": "715", "std_eind": "15.45",
        "kleur_achtergrond": "#ff0000", "kleur_tekst": "#ffffff", "vet": "1", "actief": "1"})
    code = Dienstcode.query.one()
    assert (code.std_begin, code.std_eind, code.kleur_achtergrond) == ("07:15", "15:45", "#FF0000")


def test_blanco_code_kan_geen_dienstcode_zijn(als_beheerder):
    antwoord = als_beheerder.post("/beheer/dienstcodes/nieuw",
                                  data={"nummer": "15", "omschrijving": "X"})
    assert antwoord.status_code == 400


def test_dienstcode_in_gebruik_wordt_gedeactiveerd(als_beheerder):
    laad_voorbeeldpakket()
    code = Dienstcode.query.filter_by(nummer=4).one()
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.flush()
    db.session.add(Dienst(medewerker_id=medewerker.id, datum=date(2026, 3, 2), dienstcode_id=code.id))
    db.session.commit()
    als_beheerder.post(f"/beheer/dienstcodes/{code.id}/verwijder")
    code = db.session.get(Dienstcode, code.id)
    assert code is not None and not code.actief
    ongebruikt = Dienstcode.query.filter_by(nummer=5).one()
    als_beheerder.post(f"/beheer/dienstcodes/{ongebruikt.id}/verwijder")
    assert Dienstcode.query.filter_by(nummer=5).first() is None


def test_standaardtijden_wijzigen_raakt_bestaande_diensten_niet(als_beheerder):
    laad_voorbeeldpakket()
    code = Dienstcode.query.filter_by(nummer=4).one()
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.flush()
    toekomst = date.today() + timedelta(days=7)
    dienst = Dienst(medewerker_id=medewerker.id, datum=toekomst, dienstcode_id=code.id,
                    begin="07:15", eind="15:45")
    db.session.add(dienst)
    db.session.commit()

    als_beheerder.post(f"/beheer/dienstcodes/{code.id}", data={
        "nummer": "4", "omschrijving": "VW Vroeg", "std_begin": "07:00", "std_eind": "15:30",
        "vet": "1", "actief": "1", "in_agenda": "1"})
    assert db.session.get(Dienst, dienst.id).begin == "07:15"

    # Expliciet toepassen op toekomstige diensten
    voorbeeld = als_beheerder.get(f"/beheer/dienstcodes/{code.id}/standaardtijden")
    assert b"1</strong> dienst" in voorbeeld.data
    als_beheerder.post(f"/beheer/dienstcodes/{code.id}/standaardtijden")
    dienst = db.session.get(Dienst, dienst.id)
    assert (dienst.begin, dienst.eind) == ("07:00", "15:30")


def test_vakantie_met_werkdagen(als_beheerder):
    als_beheerder.post("/beheer/vakanties/opslaan", data={
        "naam": "Kerstvakantie", "datum_van": "2026-12-19", "datum_tot": "2027-01-03"})
    assert Vakantie.query.one().datum_tot == date(2027, 1, 3)
    pagina = als_beheerder.get("/beheer/vakanties").data.decode()
    assert ">10<" in pagina  # werkdagen


def test_feestdagen_worden_per_jaar_gegenereerd(als_beheerder):
    als_beheerder.get("/beheer/feestdagen?jaar=2031")
    koningsdag = Feestdag.query.filter_by(jaar=2031, sleutel="koningsdag").one()
    assert koningsdag.datum == date(2031, 4, 26)
    als_beheerder.post(f"/beheer/feestdagen/{koningsdag.id}/wissel")
    assert not db.session.get(Feestdag, koningsdag.id).actief


def test_toeslagen_wijzigen_en_herberekenen(als_beheerder):
    medewerker = Medewerker(naam="Medewerker A", initialen="TSA")
    db.session.add(medewerker)
    db.session.flush()
    zaterdag = date(2026, 3, 7)
    dienst = Dienst(medewerker_id=medewerker.id, datum=zaterdag, begin="07:15", eind="15:45")
    bereken_dienst(dienst)
    db.session.add(dienst)
    db.session.commit()
    assert dienst.uren_berekend == 12.0

    formulier = {s: instellingen.lees(s) for s in instellingen.STANDAARD}
    formulier.update({"toeslag_zaterdag": "1,25", "eerste_jaar": "2026"})
    formulier.pop("deellink_actief")
    formulier.pop("opmerkingtijden_meetellen")
    assert als_beheerder.post("/beheer/instellingen", data=formulier).status_code == 302
    assert instellingen.lees_float("toeslag_zaterdag") == 1.25
    # Nog niet herberekend
    assert db.session.get(Dienst, dienst.id).uren_berekend == 12.0
    als_beheerder.post("/beheer/herberekenen", data={"bevestig": "1"})
    assert db.session.get(Dienst, dienst.id).uren_berekend == 10.0


def test_backup_maken_en_opruimen(app):
    import sqlite3

    from app.services import backup

    pad = backup.maak_backup("voor-update")
    assert os.path.exists(pad)
    # De kopie is een geldige database met dezelfde tabellen
    tabellen = sqlite3.connect(pad).execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    assert ("medewerker",) in tabellen
    instellingen.schrijf("backup_bewaren", "1")
    db.session.commit()
    import time

    for _ in range(2):
        backup.maak_backup()
        time.sleep(1.1)
    backup.ruim_oude_op()
    namen = [b["naam"] for b in backup.lijst_backups()]
    assert len([n for n in namen if "voor-update" in n]) == 1  # gelabelde blijft staan
    assert len(namen) == 2


def test_worker_ronde_schoont_logboek_op(app, klaar):
    from datetime import datetime

    from app.worker import Planning, een_ronde

    db.session.add(Logboek(actie="Oud", tijdstempel=datetime(2000, 1, 1)))
    db.session.commit()
    een_ronde(Planning(), nu=datetime(2026, 9, 30, 12, 0))
    assert Logboek.query.filter_by(actie="Oud").count() == 0
