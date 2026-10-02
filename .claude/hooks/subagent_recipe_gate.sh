#!/usr/bin/env bash
# SubagentStop-hook: slapper inte igenom en subagent som lamnar receptfiler
# som bryter mot receptstandarden.
#
# Exit 2 skickar agenten tillbaka till arbetet med felen som motivering.
# En rakneraknare tillater max MAX_BLOCKS blockeringar per agent, sa att en
# agent som inte klarar att ratta felen inte fastnar i en oandlig loop.
set -uo pipefail

MAX_BLOCKS=2
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
payload="$(cat)"
agent_id="$(printf '%s' "$payload" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("agent_id") or d.get("session_id") or "okand")' 2>/dev/null || echo okand)"
state_dir="${TMPDIR:-/tmp}/meal-prep-recipe-gate"
mkdir -p "$state_dir"
counter="$state_dir/$(printf '%s' "$agent_id" | tr -c 'A-Za-z0-9_.-' '_')"

cd "$PROJECT_DIR" || exit 0

# Receptfiler som agenten har skapat eller andrat. Utan git (t.ex. en zip-nedladdning)
# racknas receptfiler som andrats de senaste 3 timmarna, sa att grinden inte slapper
# igenom allt i tysthet.
recipe_re='(^|/)(recept-[^/]*\.md|04-alla-recept\.md)$|^recipe/.*\.md$'
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t files < <(
    git status --porcelain --untracked-files=all 2>/dev/null \
      | sed 's/^...//' \
      | grep -E "$recipe_re" \
      | sort -u
  )
else
  mapfile -t files < <(
    find . -path ./.git -prune -o -type f -name '*.md' -mmin -180 -print 2>/dev/null \
      | sed 's#^\./##' \
      | grep -E "$recipe_re" \
      | sort -u
  )
fi
# Raderade filer syns i git status men har inget att validera.
existing=()
for f in "${files[@]}"; do [ -f "$f" ] && existing+=("$f"); done
files=("${existing[@]}")
[ "${#files[@]}" -eq 0 ] && exit 0

output="$(python3 "$PROJECT_DIR/.claude/hooks/validate_recipe.py" --quiet "${files[@]}" 2>&1)"
[ $? -eq 0 ] && { rm -f "$counter"; exit 0; }

blocks=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$blocks" > "$counter"

if [ "$blocks" -gt "$MAX_BLOCKS" ]; then
  rm -f "$counter"
  {
    echo "Receptstandarden hittar fortfarande fel efter $MAX_BLOCKS försök."
    echo "Släpper igenom agenten — rapportera de kvarstående felen till användaren:"
    echo "$output"
  } >&2
  exit 0
fi

{
  echo "Du är inte klar: receptfilerna bryter mot .claude/rules/recipe-style.md."
  echo "$output"
  echo
  echo "Rätta varje FEL och skriv om filerna innan du avslutar."
} >&2
exit 2
