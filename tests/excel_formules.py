"""Hulpje voor de tests: de formules van een Excel-export uitrekenen zonder Excel.

We gebruiken de Python-bibliotheek 'formulas' (alleen in requirements-dev.txt). Die rekent een
heel werkboek uit met Excel-semantiek (o.a. ROUND half van nul af, 15 cijfers, tekst in SUM
genegeerd) en kent alle functies die de export gebruikt, ook NETWORKDAYS en WEEKDAY.
pycel kent NETWORKDAYS niet; daarom 'formulas'.
"""

import io
import os
import tempfile
import warnings

import openpyxl


def bereken(inhoud: bytes, wijzig: dict | None = None) -> dict:
    """Reken alle formules uit. wijzig: {'W10!D7': waarde} past eerst cellen aan (zoals in Excel).

    Geeft {'W10!F7': waarde} voor alle cellen met een formule ('' = een lege uitkomst).
    """
    import formulas

    boek = openpyxl.load_workbook(io.BytesIO(inhoud))
    for adres, waarde in (wijzig or {}).items():
        blad, cel = adres.split("!")
        boek[blad][cel].value = waarde
    with tempfile.TemporaryDirectory() as map_:
        pad = os.path.join(map_, "export.xlsx")
        boek.save(pad)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = formulas.ExcelModel().loads(pad).finish()
            uitkomst = model.calculate()
    namen = {naam.upper(): naam for naam in boek.sheetnames}  # 'formulas' schrijft ze in hoofdletters
    resultaat = {}
    for sleutel, waarde in uitkomst.items():
        if "!" not in sleutel or ":" in sleutel:
            continue
        blad, cel = sleutel.split("!")
        blad = namen.get(blad.split("]")[-1].strip("'").upper(), blad)
        waarde = getattr(waarde, "value", waarde)
        waarde = waarde[0][0] if hasattr(waarde, "__getitem__") and not isinstance(waarde, str) else waarde
        resultaat[f"{blad}!{cel}"] = _schoon(waarde)
    return resultaat


def _schoon(waarde):
    """Lege uitkomst -> '', getallen als float, fouten als tekst ('#VALUE!')."""
    tekst = str(waarde)
    if tekst in ("", "empty"):
        return ""
    if type(waarde).__name__ in ("bool", "bool_"):  # ook numpy
        return bool(waarde)
    try:
        return float(waarde)
    except (TypeError, ValueError):
        return tekst
