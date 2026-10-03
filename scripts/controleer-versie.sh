#!/bin/sh
# Versiecontrole: is VERSIE opgehoogd als de app-code veranderd is?
#
#   sh scripts/controleer-versie.sh
#
# Draait in CI op ELKE push en elk pull request (job 'versie'), dus een vergeten
# versie wordt al vóór de merge rood, niet pas op main (dan liep de release vast).
# Ook lokaal te draaien; de tags moeten er dan wel zijn (git fetch --tags).
#
# Regels:
# - Bestaat de tag v<VERSIE> al, dan mag de app-code sinds die tag niet veranderd zijn.
#   Anders: VERSIE ophogen in app/__init__.py en app/static/js/raster.js (SCRIPT_VERSIE).
# - SCRIPT_VERSIE in raster.js is gelijk aan VERSIE.
# - CHANGELOG.md heeft een kop '## [VERSIE]' (de tekst van de GitHub-release).
# Schrijft 'versie=...' en 'nieuw=true|false' naar $GITHUB_OUTPUT als die bestaat.
set -eu

# Mappen en bestanden die in de Docker-image terechtkomen
CODE="app migrations docker Dockerfile requirements.txt requirements.lock wsgi.py"

VERSIE=$(sed -n 's/^VERSIE = "\(.*\)"/\1/p' app/__init__.py)
SCRIPT=$(sed -n 's/.*var SCRIPT_VERSIE = "\(.*\)".*/\1/p' app/static/js/raster.js)
fouten=0
fout() { echo "::error::$*"; fouten=1; }

[ -n "$VERSIE" ] || { echo "::error::Geen VERSIE gevonden in app/__init__.py."; exit 1; }
[ "$SCRIPT" = "$VERSIE" ] || fout "SCRIPT_VERSIE in app/static/js/raster.js is '$SCRIPT', maar VERSIE is '$VERSIE'. Maak ze gelijk."
grep -q "^## \[$VERSIE\]" CHANGELOG.md || fout "CHANGELOG.md heeft geen kop '## [$VERSIE] – <datum>'. Zet de wijzigingen onder die kop (niet onder [Onuitgebracht])."

if [ -z "$(git tag -l 'v*')" ]; then
  echo "::warning::Geen tags gevonden (git fetch --tags); vergelijking met de vorige versie overgeslagen."
  nieuw=true
elif git rev-parse -q --verify "refs/tags/v$VERSIE" >/dev/null; then
  nieuw=false
  # shellcheck disable=SC2086  # CODE is bewust een lijst
  if ! git diff --quiet "v$VERSIE" HEAD -- $CODE; then
    fout "De code is gewijzigd, maar versie $VERSIE bestaat al (tag v$VERSIE). Verhoog VERSIE in app/__init__.py en SCRIPT_VERSIE in app/static/js/raster.js, en zet de wijzigingen in CHANGELOG.md onder '## [<nieuwe versie>] – <datum>'."
    git diff --stat "v$VERSIE" HEAD -- $CODE
  else
    echo "Versie $VERSIE heeft al een tag en de code is gelijk: geen nieuwe release."
  fi
else
  nieuw=true
  echo "Nieuwe versie: $VERSIE"
fi

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  echo "versie=$VERSIE" >> "$GITHUB_OUTPUT"
  echo "nieuw=$nieuw" >> "$GITHUB_OUTPUT"
fi
exit "$fouten"
