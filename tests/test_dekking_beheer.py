"""Beheerschermen: foutpaden en randgevallen die elders niet getest worden. Alle data is fictief."""

import io
import os
from datetime import date

from app.extensions import db
from app.models import Dienst, Dienstcode, Logboek, Medewerker, OpmerkingKleurregel
from app.services import backup
from app.services.voorbeeldpakket import laad_voorbeeldpakket

# ---------------------------------------------------------------------------
# Back-ups
# ---------------------------------------------------------------------------


def test_backup_maken_mislukt_geeft_melding(app, als_beheerder, monkeypatch):
    def vol(_label=""):
        raise OSError("schijf vol")

    monkeypatch.setattr(backup, "maak_backup", vol)
    antwoord = als_beheerder.post("/beheer/backups/maken", follow_redirects=True)
    assert "Back-up maken is mislukt: schijf vol" in antwoord.data.decode()


def test_backup_download_onbekend_geeft_404(app, als_beheerder):
    assert als_beheerder.get("/beheer/backups/download/bestaat-niet.db").status_code == 404


def test_backup_verwijderen_mislukt_geeft_melding(app, als_beheerder, monkeypatch):
    naam = os.path.basename(backup.maak_backup("handmatig"))

    def kapot(_pad):
        raise PermissionError("alleen-lezen")

    monkeypatch.setattr(os, "remove", kapot)
    antwoord = als_beheerder.post("/beheer/backups/verwijderen", data={"naam": naam}, follow_redirects=True)
    assert "Verwijderen is mislukt: alleen-lezen" in antwoord.data.decode()


def test_terugzetten_zonder_bevestiging_of_onbekend(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/backups/terugzetten", data={"naam": "x"}, follow_redirects=True)
    assert "Vink eerst de bevestiging aan" in antwoord.data.decode()
    antwoord = als_beheerder.post("/beheer/backups/terugzetten", data={"naam": "x.db", "bevestig": "1"},
                                  follow_redirects=True)
    assert "Onbekende back-up" in antwoord.data.decode()


def test_terugzetten_onverwachte_fout_ruimt_upload_op(app, als_beheerder, monkeypatch):
    def kapot(_pad):
        raise RuntimeError("onverwacht")

    monkeypatch.setattr(backup, "zet_terug", kapot)
    antwoord = als_beheerder.post("/beheer/backups/terugzetten", data={
        "bevestig": "1", "bestand": (io.BytesIO(b"iets"), "x.db")},
        content_type="multipart/form-data", follow_redirects=True)
    assert "onverwachte fout (RuntimeError)" in antwoord.data.decode()
    assert not [n for n in os.listdir(backup.backup_map()) if n.endswith("-upload.db")]
    # Een bestaande back-up blijft bij een fout gewoon staan
    naam = os.path.basename(backup.maak_backup("handmatig"))
    als_beheerder.post("/beheer/backups/terugzetten", data={"naam": naam, "bevestig": "1"})
    assert os.path.exists(os.path.join(backup.backup_map(), naam))


# ---------------------------------------------------------------------------
# Dienstcodes en kleurregels
# ---------------------------------------------------------------------------

def test_dienstcode_formulier_fouten(app, als_beheerder):
    laad_voorbeeldpakket()
    for data, melding in (
            ({"nummer": "4", "omschrijving": "Dubbel"}, "Code 4 bestaat al"),
            ({"nummer": "90", "omschrijving": ""}, "Vul een omschrijving in"),
            ({"nummer": "90", "omschrijving": "X", "std_begin": "25:99", "std_eind": "08:00"}, "tijd"),
            ({"nummer": "90", "omschrijving": "X", "std_begin": "08:00"}, "zowel een begin- als eindtijd")):
        antwoord = als_beheerder.post("/beheer/dienstcodes/nieuw", data=data)
        assert antwoord.status_code == 400 and melding in antwoord.data.decode(), data
    code = Dienstcode.query.filter_by(nummer=4).one()
    antwoord = als_beheerder.post(f"/beheer/dienstcodes/{code.id}", data={"nummer": "5", "omschrijving": "X"})
    assert antwoord.status_code == 400 and "Code 5 bestaat al" in antwoord.data.decode()
    pagina = als_beheerder.get(f"/beheer/dienstcodes/{code.id}").data.decode()
    assert f'value="{code.omschrijving}"' in pagina


def test_hernoemen_laat_andere_dienstnaam_staan(app, als_beheerder):
    laad_voorbeeldpakket()
    code = Dienstcode.query.filter_by(nummer=4).one()
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.flush()
    db.session.add(Dienst(medewerker_id=medewerker.id, datum=date(2026, 3, 2), dienstcode_id=code.id,
                          dienstnaam_override="Iets heel anders"))
    db.session.commit()
    als_beheerder.post(f"/beheer/dienstcodes/{code.id}", data={
        "nummer": "4", "omschrijving": "Ochtend", "std_begin": code.std_begin, "std_eind": code.std_eind,
        "actief": "1", "in_agenda": "1"})
    assert Dienst.query.one().dienstnaam_override == "Iets heel anders"


def test_voorbeeldpakket_en_kleurregels(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/dienstcodes/voorbeeldpakket", follow_redirects=True)
    assert "dienstcodes en" in antwoord.data.decode() and Dienstcode.query.count() > 0
    assert Logboek.query.filter_by(actie="Dienstcodes").count() == 1
    antwoord = als_beheerder.post("/beheer/kleurregels/nieuw", data={"tekst": " "}, follow_redirects=True)
    assert "Vul een tekst in" in antwoord.data.decode()
    als_beheerder.post("/beheer/kleurregels/nieuw", data={"tekst": "Testregel"})
    regel = OpmerkingKleurregel.query.filter_by(tekst="Testregel").one()
    antwoord = als_beheerder.post(f"/beheer/kleurregels/{regel.id}/verwijder", follow_redirects=True)
    assert "Kleurregel verwijderd" in antwoord.data.decode()
    assert OpmerkingKleurregel.query.filter_by(tekst="Testregel").first() is None
    assert als_beheerder.post("/beheer/kleurregels/99999/verwijder").status_code == 404


# ---------------------------------------------------------------------------
# Medewerkers
# ---------------------------------------------------------------------------

def test_medewerker_formulier_fouten(app, als_beheerder):
    for data, melding in (({"naam": ""}, "Vul een naam in"),
                          ({"naam": "Medewerker A", "initialen": "!!"}, "nitialen"),
                          ({"naam": "Medewerker A", "email": "geen-adres"}, "e-mailadres is ongeldig"),
                          ({"naam": "Medewerker A", "cu_jaar_1": "abc", "cu_uren_1": "10"}, "Contracturen")):
        antwoord = als_beheerder.post("/beheer/medewerkers/nieuw", data=data)
        assert antwoord.status_code == 400 and melding in antwoord.data.decode(), data
    assert Medewerker.query.count() == 0


def test_medewerker_wijzigen_contracturen_en_formulier(app, als_beheerder):
    als_beheerder.post("/beheer/medewerkers/nieuw", data={
        "naam": "Medewerker A", "initialen": "MA", "cu_jaar_1": "2025", "cu_uren_1": "1000",
        "cu_jaar_2": "2026", "cu_uren_2": "1200", "cu_jaar_3": "2027", "cu_uren_3": ""})
    medewerker = Medewerker.query.one()
    assert {c.jaar: c.uren for c in medewerker.contracturen} == {2025: 1000, 2026: 1200}
    url = f"/beheer/medewerkers/{medewerker.id}"
    pagina = als_beheerder.get(url).data.decode()
    assert 'value="Medewerker A"' in pagina and "1200" in pagina
    # 2025 weg, 2026 gewijzigd, naam gelijk (geen agenda-hersync)
    antwoord = als_beheerder.post(url, data={"naam": "Medewerker A", "initialen": "MA",
                                             "cu_jaar_1": "2026", "cu_uren_1": "1300"})
    assert antwoord.status_code == 302
    db.session.expire_all()
    assert {c.jaar: c.uren for c in Medewerker.query.one().contracturen} == {2026: 1300}
    assert Logboek.query.filter_by(actie="Contracturen verwijderd").count() == 1
    assert Logboek.query.filter_by(actie="Contracturen gewijzigd", oude_waarde="1200.0").count() == 1
    als_beheerder.post(url, data={"naam": "Medewerker A", "initialen": "MA", "cu_jaar_1": "2026",
                                  "cu_uren_1": "1300"})  # ongewijzigd: geen nieuwe logboekregel
    assert Logboek.query.filter_by(actie="Contracturen gewijzigd", oude_waarde="1300.0").count() == 0
    antwoord = als_beheerder.post(url, data={"naam": "", "initialen": "MA"})
    assert antwoord.status_code == 400


def test_verplaatsen_randen_en_onbekend(app, als_beheerder):
    for naam, init in (("Medewerker A", "MA"), ("Medewerker B", "MB")):
        als_beheerder.post("/beheer/medewerkers/nieuw", data={"naam": naam, "initialen": init})
    a = Medewerker.query.filter_by(initialen="MA").one()
    als_beheerder.post(f"/beheer/medewerkers/{a.id}/verplaats", data={"richting": "omhoog"})  # al bovenaan
    assert als_beheerder.post("/beheer/medewerkers/99999/verplaats").status_code == 302
    assert [m.initialen for m in Medewerker.query.order_by(Medewerker.volgorde)] == ["MA", "MB"]
    assert Logboek.query.filter_by(actie="Volgorde gewijzigd").count() == 0


def test_archiveren_met_agenda_en_herstellen(app, als_beheerder):
    from app.models import SyncTaak

    medewerker = Medewerker(naam="Medewerker A", initialen="MA", agenda_modus="B", agenda_id="agenda-a")
    db.session.add(medewerker)
    db.session.commit()
    url = f"/beheer/medewerkers/{medewerker.id}/archiveer"
    als_beheerder.post(url, data={"vanaf": "2026-06-01", "agenda": "verwijderen"})
    assert SyncTaak.query.filter_by(soort="ontkoppel").count() == 1
    assert db.session.get(Medewerker, medewerker.id).agenda_modus == ""
    antwoord = als_beheerder.post(url, data={"herstel": "1"}, follow_redirects=True)
    assert "is weer actief" in antwoord.data.decode()
    assert db.session.get(Medewerker, medewerker.id).gearchiveerd_vanaf is None


def test_verwijderpagina_tonen(app, als_beheerder):
    medewerker = Medewerker(naam="Medewerker A", initialen="MA")
    db.session.add(medewerker)
    db.session.commit()
    pagina = als_beheerder.get(f"/beheer/medewerkers/{medewerker.id}/verwijder")
    assert pagina.status_code == 200 and "Medewerker A" in pagina.data.decode()


# ---------------------------------------------------------------------------
# Excel-import: foutpaden van het scherm
# ---------------------------------------------------------------------------

def test_import_zonder_of_met_verkeerd_bestand(app, als_beheerder):
    antwoord = als_beheerder.post("/beheer/importeren", data={}, follow_redirects=True)
    assert "Kies een Excel-bestand" in antwoord.data.decode()
    antwoord = als_beheerder.post("/beheer/importeren", data={"bestand": (io.BytesIO(b"x"), "rooster.pdf")},
                                  content_type="multipart/form-data", follow_redirects=True)
    assert "Kies een Excel-bestand" in antwoord.data.decode()
    for url in ("/beheer/importeren/jaar", "/beheer/importeren/voorbeeld"):
        antwoord = als_beheerder.post(url, data={"jaar": "2026"}, follow_redirects=True)
        assert "Upload eerst een bestand" in antwoord.data.decode(), url


def test_import_stappen_foutpaden(app, als_beheerder, tmp_path, monkeypatch):
    from app.blueprints.beheer import importeren
    from app.services.excel_import import ImportFout

    from .test_import_backup import keuzeformulier, maak_testbestand, upload

    pad = str(tmp_path / "rooster.xlsx")
    maak_testbestand(pad)
    upload(als_beheerder, pad, jaar=2026)
    als_beheerder.post("/beheer/importeren/jaar", data={"jaar": "2026"})  # zelfde jaar: keuzes blijven
    pagina = als_beheerder.get("/beheer/importeren/voorbeeld").data.decode()
    assert "Voorbeeld (droogloop)" in pagina
    # Ongeldige periode
    antwoord = als_beheerder.post("/beheer/importeren/voorbeeld",
                                  data={**keuzeformulier(actie="voorbeeld"), "van": "onzin"},
                                  follow_redirects=True)
    assert "Vul een geldige periode in" in antwoord.data.decode()
    # Zonder bevestiging
    als_beheerder.post("/beheer/importeren/voorbeeld", data=keuzeformulier(actie="voorbeeld"))
    antwoord = als_beheerder.post("/beheer/importeren/voorbeeld", data=keuzeformulier(bevestig=False),
                                  follow_redirects=True)
    assert "Vink eerst de bevestiging aan" in antwoord.data.decode()
    # Onverwachte fout bij het importeren: nette melding, niets geïmporteerd
    monkeypatch.setattr(importeren, "importeer", lambda *_: (_ for _ in ()).throw(RuntimeError("weg")))
    antwoord = als_beheerder.post("/beheer/importeren/voorbeeld", data=keuzeformulier(),
                                  follow_redirects=True)
    assert "De import is mislukt; er is niets geïmporteerd (RuntimeError)" in antwoord.data.decode()
    assert Dienst.query.count() == 0
    # Bewaarde keuzes die niet meer kloppen: terug naar de standaard
    with als_beheerder.session_transaction() as sessie:
        sessie["import_keuzes"] = {**sessie["import_keuzes"], "modus": "onbekend"}
    assert "Voorbeeld (droogloop)" in als_beheerder.get("/beheer/importeren/voorbeeld").data.decode()
    # Het bestand is intussen onleesbaar geworden
    monkeypatch.setattr(importeren, "lees_bestand", lambda *_: (_ for _ in ()).throw(ImportFout("kapot")))
    antwoord = als_beheerder.get("/beheer/importeren/voorbeeld", follow_redirects=True)
    assert "kapot" in antwoord.data.decode()
    assert "Upload eerst een bestand" in als_beheerder.post("/beheer/importeren/voorbeeld",
                                                            follow_redirects=True).data.decode()


def test_import_annuleren(app, als_beheerder, tmp_path):
    from .test_import_backup import maak_testbestand, upload

    pad = str(tmp_path / "rooster.xlsx")
    maak_testbestand(pad)
    upload(als_beheerder, pad, jaar=None)
    antwoord = als_beheerder.post("/beheer/importeren/annuleren", follow_redirects=True)
    assert "Import geannuleerd" in antwoord.data.decode()
    assert os.listdir(os.path.join(app.config["DATA_MAP"], "import")) == []


# ---------------------------------------------------------------------------
# Gebruikers, instellingen, vakanties/feestdagen, logboek
# ---------------------------------------------------------------------------

def test_eigen_account_wijzigen_houdt_sessie_geldig(app, als_beheerder, klaar):
    eigen = klaar["beheerder"]
    antwoord = als_beheerder.post(f"/beheer/gebruikers/{eigen.id}", data={
        "gebruikersnaam": "beheerder", "weergavenaam": "Nieuwe naam", "rol": "beheerder", "actief": "1"})
    assert antwoord.status_code == 302
    assert als_beheerder.get("/beheer/gebruikers").status_code == 200  # nog steeds ingelogd


def test_laatste_beheerder_verwijderen_geweigerd(app, als_beheerder, klaar, monkeypatch):
    from app.blueprints.beheer import gebruikers

    from .conftest import maak_gebruiker

    andere = maak_gebruiker("tweede", "beheerder")
    url = f"/beheer/gebruikers/{andere.id}/verwijder"
    monkeypatch.setattr(gebruikers, "_aantal_actieve_beheerders", lambda behalve_id: 0)
    antwoord = als_beheerder.post(url, follow_redirects=True)
    assert "De laatste beheerder kan niet verwijderd worden" in antwoord.data.decode()
    # Gelijktijdig de andere beheerder weg (controle binnen de transactie): niets verwijderd
    monkeypatch.setattr(gebruikers, "_aantal_actieve_beheerders", lambda behalve_id: 1)
    monkeypatch.setattr(gebruikers, "_nog_een_beheerder", lambda: db.session.rollback() or False)
    antwoord = als_beheerder.post(url, follow_redirects=True)
    assert "De laatste beheerder kan niet verwijderd worden" in antwoord.data.decode()
    from app.models import Gebruiker
    assert db.session.get(Gebruiker, andere.id) is not None


def _instellingen(**extra):
    from app.services import instellingen

    data = {s: instellingen.lees(s) for s in instellingen.STANDAARD}
    data.update(teamnaam="Team", tijdzone="Europe/Amsterdam", toeslag_zaterdag="1.5", toeslag_zondag="2",
                eerste_jaar="2026", blanco_code="")
    data.update(extra)
    return data


def test_instellingen_fouten_en_deellink(app, als_beheerder):
    from app.services import instellingen

    for extra, melding in (({"teamnaam": ""}, "Vul een teamnaam in"),
                           ({"logboek_dagen": "abc"}, "Ongeldige waarde voor")):
        antwoord = als_beheerder.post("/beheer/instellingen", data=_instellingen(**extra))
        assert antwoord.status_code == 400 and melding in antwoord.data.decode(), extra
    antwoord = als_beheerder.post("/beheer/instellingen", data=_instellingen(
        feestdagtoeslag_aan="1", toeslag_feestdag="1,75", deellink_actief="1"))
    assert antwoord.status_code == 302
    assert instellingen.lees("toeslag_feestdag") == "1.75" and instellingen.lees("deellink_token")
    oud = instellingen.lees("deellink_token")
    antwoord = als_beheerder.post("/beheer/instellingen/deellink-vernieuwen", follow_redirects=True)
    assert "nieuwe deellink" in antwoord.data.decode() and instellingen.lees("deellink_token") != oud
    antwoord = als_beheerder.post("/beheer/herberekenen", data={}, follow_redirects=True)
    assert "Vink eerst de bevestiging aan" in antwoord.data.decode()


def test_instellingen_voorvoegsel_plant_agenda(app, als_beheerder):
    from app.models import SyncTaak

    db.session.add(Medewerker(naam="Medewerker A", initialen="MA", agenda_modus="B", agenda_id="x"))
    db.session.commit()
    antwoord = als_beheerder.post("/beheer/instellingen", data=_instellingen(agenda_voorvoegsel="[Werk]"))
    assert antwoord.status_code == 302, antwoord.data.decode()[-3000:]
    assert SyncTaak.query.filter_by(soort="volledig").count() == 1


def test_vakantie_wijzigen_en_fouten(app, als_beheerder):
    from app.models import Vakantie

    for data, melding in (({"naam": "", "datum_van": "2026-07-01", "datum_tot": "2026-07-10"},
                           "Vul een naam"),
                          ({"naam": "X", "datum_van": "2026-07-10", "datum_tot": "2026-07-01"},
                           "voor de begin")):
        antwoord = als_beheerder.post("/beheer/vakanties/opslaan", data=data, follow_redirects=True)
        assert melding in antwoord.data.decode(), data
    als_beheerder.post("/beheer/vakanties/opslaan", data={"naam": "Zomer", "datum_van": "2026-07-01",
                                                  "datum_tot": "2026-07-10"})
    vakantie = Vakantie.query.one()
    als_beheerder.post("/beheer/vakanties/opslaan", data={"id": vakantie.id, "naam": "Zomer lang",
                                                  "datum_van": "2026-07-01", "datum_tot": "2026-07-20"})
    db.session.expire_all()
    assert (Vakantie.query.one().naam, Vakantie.query.one().datum_tot) == ("Zomer lang", date(2026, 7, 20))
    assert Logboek.query.filter_by(actie="Vakantie gewijzigd").count() == 1


def test_feestdag_fouten(app, als_beheerder):
    from app.models import Feestdag
    from app.services.feestdagen import zorg_voor_jaar

    antwoord = als_beheerder.post("/beheer/feestdagen/nieuw", data={"naam": "", "datum": "2026-05-01"},
                                  follow_redirects=True)
    assert "Vul een naam en een geldige datum in" in antwoord.data.decode()
    zorg_voor_jaar(2026)
    db.session.commit()
    standaard = Feestdag.query.filter(Feestdag.sleutel != "").first()
    antwoord = als_beheerder.post(f"/beheer/feestdagen/{standaard.id}/verwijder", follow_redirects=True)
    assert "Standaard feestdagen kun je alleen uitzetten" in antwoord.data.decode()


def test_logboek_filters(app, als_beheerder):
    from app.services import logboek

    logboek.log("Testactie", "details")
    db.session.commit()
    pagina = als_beheerder.get("/beheer/logboek?gebruiker=beheerder&actie=Testactie"
                               "&van=2000-01-01&tot=2100-01-01")
    assert pagina.status_code == 200
