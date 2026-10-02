#!/usr/bin/env bash
# SessionStart-hook: paminner om /setup nar ingen hushallsprofil finns, och varnar om
# verktyg som hookarna behover saknas. Stdout blir kontext for Claude. Avslutar alltid
# med 0 -- hooken far aldrig hindra en session fran att starta.
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Varning: python3 saknas. Receptstandarden kontrolleras inte förrän python3 (3.8+) är installerat — säg det till användaren."
fi
if ! git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Notis: projektet är inte ett git-repo (t.ex. nedladdat som zip). Klona hellre med git; receptgrinden fungerar sämre utan."
fi
if [ ! -f "$PROJECT_DIR/meal-prep.local.yaml" ]; then
  echo "Ingen hushållsprofil (meal-prep.local.yaml) finns ännu. Föreslå att användaren kör /setup innan matplanering — utan den gäller standardvärdena i meal-prep.example.yaml (4 portioner, middag, inga tillval)."
fi
exit 0
