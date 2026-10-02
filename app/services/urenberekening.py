"""Urenberekening, exact volgens de oude Excel-VBA (sub UrenBerekening).

Stappen per dag (alleen de tijdenregel telt):
1. begin en eind afronden op hele minuten
2. eind < begin  -> eind + 24 uur (nachtdienst over middernacht)
3. uren = eind - begin
4. pauze: uren > 5,5 -> 0,5 uur eraf (standaard, zie STANDAARD_PAUZE)
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

Pauze (sinds 1.6.0 instelbaar in Beheer → Instellingen): een staffel met regels "meer dan
X uur gewerkt: Y uur eraf". De hoogste regel die van toepassing is telt (niet optellen);
precies op de grens telt niet. De pauze geldt per dag (sinds 1.8.3): bij twee diensten,
of een dienst plus meetellende opmerkingtijden, gaat de pauze één keer af van het totaal
van de dag, bij het langste deel (zie rooster.dag_uren; die delen rekenen exact, zie
uren_exact). De standaard is nog steeds de
Excel-VBA: één regel, meer dan 5,5 uur -> 0,5 eraf. Pauzeaftrek uit = een lege staffel.

Zomer-/wintertijd: we rekenen met wandkloktijd, net als Excel. Een nachtdienst
22:00-06:30 telt dus altijd 8,00 uur, ook in de nacht dat de klok verzet wordt.
"""

from datetime import date
from fractions import Fraction

from .tijden import tijd_naar_minuten

# Pauzestaffel: ((grens, aftrek), ...) met oplopende grenzen; () = geen pauzeaftrek
Staffel = tuple[tuple[float, float], ...]
STANDAARD_PAUZE: Staffel = ((5.5, 0.5),)  # meer dan 5,5 uur -> 0,5 eraf (de oude VBA)


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


def pauze_aftrek(uren: float, staffel: Staffel) -> float:
    """De pauze die eraf gaat: de aftrek van de hoogste grens die overschreden is (anders 0).

    Precies op de grens telt niet (net als 'uren > 5,5' in de VBA).
    """
    aftrek = 0.0
    for grens, regel_aftrek in staffel:  # grenzen staan oplopend
        if uren > grens:
            aftrek = regel_aftrek
    return aftrek


def bereken_uren(begin: str | None, eind: str | None, factor: float = 1.0,
                 pauze: Staffel = STANDAARD_PAUZE) -> float | None:
    """Bereken de uren van één dag, precies zoals de Excel-VBA.

    begin/eind: 'HH:MM' of None. factor: zie dagfactor(). pauze: de pauzestaffel.
    Geeft None als begin of eind ontbreekt.
    """
    begin_min = tijd_naar_minuten(begin)
    eind_min = tijd_naar_minuten(eind)
    if begin_min is None or eind_min is None:
        return None
    return uren_uit_minuten(begin_min, eind_min, factor, pauze)


def gewerkte_minuten(begin_min: int, eind_min: int) -> int:
    """Gewerkte minuten van begin tot eind (eind vóór begin = over middernacht)."""
    return (eind_min - begin_min) % 1440


def uren_exact(minuten: int, factor: float, aftrek: float) -> float:
    """(minuten - aftrek) × factor, exact gerekend en op kwartieren afgerond (half naar even).

    Voor een deel van een dag met meer delen (zie rooster.dag_uren): daar bestaat geen oude
    VBA om na te bootsen, dus geen kommagetallen. Zo rekent de Excel-export ook.
    """
    x = (Fraction(minuten, 60) - Fraction(str(aftrek))) * Fraction(str(factor)) * 4
    return round(x) / 4  # round() op een Fraction: exact, half naar even


def uren_uit_minuten(begin_min: int, eind_min: int, factor: float = 1.0,
                     pauze: Staffel = STANDAARD_PAUZE) -> float:
    """bereken_uren vanaf minuten sinds middernacht (ook gebruikt door de Excel-export)."""

    # Stap 1: tijden als fractie van een dag, afgerond op hele minuten (zoals VBA)
    dbl_begin = round(begin_min / 1440 * 1440) / 1440
    dbl_eind = round(eind_min / 1440 * 1440) / 1440

    # Stap 2: over middernacht
    if dbl_eind < dbl_begin:
        dbl_eind = dbl_eind + 1

    # Stap 3: verschil in uren
    uren = (dbl_eind - dbl_begin) * 24

    # Stap 4: pauze-aftrek (zonder aftrek blijft het getal precies gelijk, zoals in de VBA)
    aftrek = pauze_aftrek(uren, pauze)
    if aftrek:
        uren = uren - aftrek

    # Stap 5 + 6: factor en afronden op kwartieren (bankiersafronding, zie boven)
    return round(uren * factor * 4) / 4


def formatteer_uren(uren: float | None) -> str:
    """8.25 -> '8,25'; None -> ''."""
    if not isinstance(uren, (int, float)):  # None of leeg (ook vanuit templates)
        return ""
    return f"{uren:.2f}".replace(".", ",")
