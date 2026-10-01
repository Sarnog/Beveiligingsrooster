"""Maak de app-iconen (PNG) uit app/static/favicon.svg, met de browser van Playwright.

Geen externe diensten: Chromium tekent de SVG en maakt er een schermafbeelding van.
    pip install -r requirements-dev.txt && python -m playwright install chromium
    python scripts/maak-iconen.py

Uitvoer in app/static/icons/:
    icoon-192.png, icoon-512.png      gewone iconen (ronde hoeken, zoals het favicon)
    icoon-maskable-512.png            Android 'maskable': ontwerp binnen de veilige zone (80 %)
    apple-touch-icon.png (180 × 180)  iOS: vierkant en zonder transparantie
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

MAP = Path(__file__).resolve().parent.parent / "app" / "static"
ACHTERGROND = "#16325c"

# (bestand, maat, schaal van het ontwerp, met effen achtergrond)
ICONEN = [
    ("icoon-192.png", 192, 1.0, False),
    ("icoon-512.png", 512, 1.0, False),
    ("icoon-maskable-512.png", 512, 0.7, True),
    ("apple-touch-icon.png", 180, 0.85, True),
]


def main() -> None:
    svg = (MAP / "favicon.svg").read_text(encoding="utf-8")
    uit = MAP / "icons"
    uit.mkdir(exist_ok=True)
    pad = os.environ.get("PLAYWRIGHT_CHROMIUM") or "/opt/pw-browsers/chromium"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=pad if os.path.exists(pad) else None)
        for naam, maat, schaal, effen in ICONEN:
            pagina = browser.new_page(viewport={"width": maat, "height": maat})
            binnen = round(maat * schaal)
            pagina.set_content(
                f'<html><body style="margin:0;width:{maat}px;height:{maat}px;display:grid;'
                f'place-items:center;background:{ACHTERGROND if effen else "transparent"}">'
                f'<div style="width:{binnen}px;height:{binnen}px">{svg}</div></body></html>')
            pagina.locator("svg").evaluate("el => { el.style.width = '100%'; el.style.height = '100%'; }")
            pagina.screenshot(path=str(uit / naam), omit_background=not effen)
            pagina.close()
            print(f"{naam}: {maat} × {maat}")
        browser.close()


if __name__ == "__main__":
    main()
