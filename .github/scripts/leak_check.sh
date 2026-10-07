#!/usr/bin/env bash
# Stoppar personliga data från att hamna i det publika repot: Notion-id:n, lokala
# hemkataloger, e-postadresser och spårade filer som ska vara gitignorerade.
# Körs i CI och går att köra lokalt: bash .github/scripts/leak_check.sh
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

status=0
fail() { echo "::error::$1"; status=1; }

# Filer som aldrig ska vara spårade.
tracked="$(git ls-files | grep -E '(^|/)\.env$|(^|/)\.env\.[^e]|\.local\.(yaml|md|json)$|^20[0-9]{2}-[0-9]{2}-[0-9]{2}/' || true)"
[ -n "$tracked" ] && fail "Personliga filer är spårade (ska vara gitignorerade):
$tracked"

# Innehåll. Skriptet självt undantas.
files="$(git ls-files | grep -v '^\.github/scripts/leak_check\.sh$')"
check() {  # $1 = beskrivning, $2 = regex
  hits="$(printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 grep -nIE "$2" -- 2>/dev/null || true)"
  [ -n "$hits" ] && fail "$1:
$hits"
}
check "Notion data source-id" 'collection://[0-9a-f]{8}-'
check "Notion-sid-id i URL" 'notion\.(so|site|com)/[^ )]*[0-9a-f]{32}'
check "Lokal hemkatalog" '/(Users|home)/[a-z][a-z0-9_-]+/(Projects|Documents|Desktop|conductor)'
check "E-postadress" '[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|icloud|yahoo|live|me)\.[a-z]{2,}'

[ "$status" -eq 0 ] && echo "Inga läckor hittade."
exit "$status"
