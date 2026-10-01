"""Kalenderlogica: ISO-weken, Pasen, Nederlandse feestdagen en werkdagen.

ISO 8601: de week begint op maandag en week 1 is de week met 4 januari.
Week 1 kan dus in december van het vorige jaar beginnen (2026: maandag 29-12-2025).
"""

from datetime import date, timedelta

DAGNAMEN_KORT = ["ma", "di", "wo", "do", "vr", "za", "zo"]
DAGNAMEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MIN_JAAR, MAX_JAAR = 1950, 2150  # redelijke grenzen voor jaartallen in de app
MAANDNAMEN = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]


def aantal_weken(jaar: int) -> int:
    """52 of 53. Een jaar heeft 53 ISO-weken als 28 december in week 53 valt."""
    return 53 if date(jaar, 12, 28).isocalendar()[1] == 53 else 52


def maandag_van_week(jaar: int, week: int) -> date:
    """De maandag van ISO-week `week` in ISO-jaar `jaar`."""
    return date.fromisocalendar(jaar, week, 1)


def week_van(datum: date) -> tuple[int, int]:
    """(iso_jaar, iso_week) van een datum."""
    iso = datum.isocalendar()
    return iso[0], iso[1]


def dagen_van_week(jaar: int, week: int) -> list[date]:
    """De 7 datums (ma t/m zo) van een ISO-week."""
    maandag = maandag_van_week(jaar, week)
    return [maandag + timedelta(days=i) for i in range(7)]


def eerste_en_laatste_dag_isojaar(jaar: int) -> tuple[date, date]:
    """Eerste maandag van week 1 en laatste zondag van de laatste week."""
    eerste = maandag_van_week(jaar, 1)
    laatste = maandag_van_week(jaar, aantal_weken(jaar)) + timedelta(days=6)
    return eerste, laatste


def pasen(jaar: int) -> date:
    """Paaszondag volgens het anonieme Gregoriaanse algoritme (Meeus/Jones/Butcher).

    Dit is dezelfde berekening als BerekenPaasdatum in de oude VBA.
    """
    a = jaar % 19
    b = jaar // 100
    c = jaar % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    lw = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lw) // 451
    maand = (h + lw - 7 * m + 114) // 31
    dag = ((h + lw - 7 * m + 114) % 31) + 1
    return date(jaar, maand, dag)


def koningsdag(jaar: int) -> date:
    """27 april, of 26 april als 27 april op een zondag valt."""
    dag = date(jaar, 4, 27)
    if dag.weekday() == 6:
        return date(jaar, 4, 26)
    return dag


def nederlandse_feestdagen(jaar: int) -> list[tuple[str, str, date]]:
    """Alle standaard feestdagen van een jaar als (sleutel, naam, datum)."""
    paas = pasen(jaar)
    return [
        ("nieuwjaarsdag", "Nieuwjaarsdag", date(jaar, 1, 1)),
        ("goede_vrijdag", "Goede Vrijdag", paas - timedelta(days=2)),
        ("eerste_paasdag", "1e Paasdag", paas),
        ("tweede_paasdag", "2e Paasdag", paas + timedelta(days=1)),
        ("koningsdag", "Koningsdag", koningsdag(jaar)),
        ("bevrijdingsdag", "Bevrijdingsdag", date(jaar, 5, 5)),
        ("hemelvaartsdag", "Hemelvaartsdag", paas + timedelta(days=39)),
        ("eerste_pinksterdag", "1e Pinksterdag", paas + timedelta(days=49)),
        ("tweede_pinksterdag", "2e Pinksterdag", paas + timedelta(days=50)),
        ("eerste_kerstdag", "1e Kerstdag", date(jaar, 12, 25)),
        ("tweede_kerstdag", "2e Kerstdag", date(jaar, 12, 26)),
    ]


def werkdagen(van: date, tot: date) -> int:
    """Aantal werkdagen (ma-vr) van `van` t/m `tot`, zoals NETWORKDAYS in Excel.

    Is `tot` eerder dan `van`, dan is de uitkomst negatief (net als in Excel).
    """
    if tot < van:
        return -werkdagen(tot, van)
    aantal = 0
    dag = van
    while dag <= tot:
        if dag.weekday() < 5:
            aantal += 1
        dag += timedelta(days=1)
    return aantal


def maand_raster(jaar: int, maand: int) -> list[list[date | None]]:
    """Weken van een maand als lijst van 7 dagen (None buiten de maand).

    Gebruikt voor de jaarkalender (12 maandblokken).
    """
    eerste = date(jaar, maand, 1)
    start = eerste - timedelta(days=eerste.weekday())
    weken = []
    dag = start
    while True:
        week = []
        for _ in range(7):
            week.append(dag if dag.month == maand else None)
            dag += timedelta(days=1)
        weken.append(week)
        if dag.month != maand or dag.year != jaar:
            break
    return weken
