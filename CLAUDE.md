# Beveiligingsrooster – afspraken

- Alles in het Nederlands: code, commentaar, teksten, commits en CHANGELOG.
- Tests: `pytest -q -m "not browser"` (CI eist 100% branch-coverage) en `ruff check .`.

## Versie en release (VERPLICHT bij elke wijziging aan de app)

Een push naar main publiceert alleen een release als `VERSIE` nieuw is. Is de code gewijzigd
maar de versie niet opgehoogd, dan loopt CI op main vast. Dus bij **elke** branch die iets wijzigt
in `app/`, `migrations/`, `docker/`, `Dockerfile`, `requirements*.txt/.lock` of `wsgi.py`:

1. Verhoog `VERSIE` in `app/__init__.py` (patch voor fixes, minor voor nieuwe functies).
2. Zet `SCRIPT_VERSIE` in `app/static/js/raster.js` op hetzelfde nummer.
3. Zet de wijzigingen in `CHANGELOG.md` onder `## [<VERSIE>] – <JJJJ-MM-DD>`, niet onder
   `[Onuitgebracht]` (de release-tekst komt uit die kop).
4. Zet het nummer in de eerste regel van `docs/handleiding-*.md` ook op de nieuwe versie.
5. Controleer vóór het pushen: `git fetch --tags && sh scripts/controleer-versie.sh`.

Is de vorige branch al gemerged, dan is de versie daarvan al uitgebracht (tag `v<VERSIE>`):
een vervolgwijziging krijgt weer een nieuw nummer.
