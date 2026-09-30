"""Urenberekening, exact volgens de oude Excel-VBA (sub UrenBerekening).

Stappen per dag (alleen de tijdenregel telt):
1. begin en eind afronden op hele minuten
2. eind < begin  -> eind + 24 uur (nachtdienst over middernacht)
3. uren = eind - begin
4. uren > 5,5    -> 0,5 uur pauze eraf
5. factor: zaterdag / zondag uit de instellingen, anders 1
   (optioneel: feestdagfactor; de hoogste factor telt, er wordt niet vermenigvuldigd)
6. afronden op kwartieren: round(uren * factor * 4) / 4
7. geen begin- of eindtijd -> geen uren (None)

LET OP afronding: VBA's Round() rondt 'bankiers' af (half naar even: 2,5 -> 2, 3,5 -> 4).
Python's round() doet precies hetzelfde. Dat is bewust zo gehouden, zodat de uitkomst
gelijk is aan het Excel-bestand.

We rekenen ook met dezelfde tussenstappen als Excel (tijden als fractie van een dag),
zodat eventuele afrondingsverschillen van kommagetallen identiek zijn. Dat is
belangrijk bij weekenddiensten: 1:15 uur x 1,5 x 4 = precies 7,5 op papier, maar
als kommagetal soms 7,4999... of 7,5000...1. Excel rondt dan af naar 7 of 8, en
wij dus ook, exact hetzelfde. Gecontroleerd tegen 1899 diensten uit het oude
Excel-bestand: alle uitkomsten gelijk (op 5 cellen na waarin de planner de uren
met de hand had aangepast; die worden bij de import als 'zelf ingevulde uren'
overgenomen).

Zomer-/wintertijd: we rekenen met wandkloktijd, net als Excel. Een nachtdienst
22:00-06:30 telt dus altijd 8,00 uur, ook in de nacht dat de klok verzet wordt.
"""

from datetime import date

from .tijden import tijd_naar_minuten

PAUZE_GRENS = 5.5  # meer dan zoveel uur -> pauze-aftrek
PAUZE_AFTREK = 0.5


def dagfactor(
    datum_of_weekdag: date | int,
    factor_zaterdag: float = 1.5,
    factor_zondag: float = 2.0,
    is_feestdag: bool = False,
    factor_feestdag: float | None = None,
) -> float:
    """Bepaal de toeslagfactor voor een dag.

    datum_of_weekdag: een datum, of een weekdagnummer (0 = maandag ... 6 = zondag).
    Een feestdag krijgt alleen een toeslag als factor_feestdag is ingesteld.
    Valt een feestdag in het weekend, dan telt de hoogste factor.
    """
    weekdag = (
        datum_of_weekdag.weekday() if isinstance(datum_of_weekdag, date) else datum_of_weekdag
    )
    if weekdag == 5:
        factor = factor_zaterdag
    elif weekdag == 6:
        factor = factor_zondag
    else:
        factor = 1.0
    if is_feestdag and factor_feestdag:
        factor = max(factor, factor_feestdag)
    return factor


def bereken_uren(begin: str | None, eind: str | None, factor: float = 1.0) -> float | None:
    """Bereken de uren van één dag, precies zoals de Excel-VBA.

    begin/eind: 'HH:MM' of None. factor: zie dagfactor().
    Geeft None als begin of eind ontbreekt.
    """
    begin_min = tijd_naar_minuten(begin)
    eind_min = tijd_naar_minuten(eind)
    if begin_min is None or eind_min is None:
        return None

    # Stap 1: tijden als fractie van een dag, afgerond op hele minuten (zoals VBA)
    dbl_begin = round(begin_min / 1440 * 1440) / 1440
    dbl_eind = round(eind_min / 1440 * 1440) / 1440

    # Stap 2: over middernacht
    if dbl_eind < dbl_begin:
        dbl_eind = dbl_eind + 1

    # Stap 3: verschil in uren
    uren = (dbl_eind - dbl_begin) * 24

    # Stap 4: pauze-aftrek
    if uren > PAUZE_GRENS:
        uren = uren - PAUZE_AFTREK

    # Stap 5 + 6: factor en afronden op kwartieren (bankiersafronding, zie boven)
    return round(uren * factor * 4) / 4


def formatteer_uren(uren: float | None) -> str:
    """8.25 -> '8,25'; None -> ''."""
    if not isinstance(uren, (int, float)):  # None of leeg (ook vanuit templates)
        return ""
    return f"{uren:.2f}".replace(".", ",")
