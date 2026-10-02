#!/usr/bin/env bash
# PreToolUse-hook for mathem-matcher och mathem-granskare (matcher "Write").
#
# Agenterna far bara skriva sina svarsfiler:
#   .../.mathem-matchning/omgang-1|2/batch-NN.json eller granskning.json
# Exit 0 = tillatet. Exit 2 = blockerat, stderr skickas tillbaka till agenten.
set -uo pipefail

payload="$(cat)"
file_path="$(printf '%s' "$payload" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path") or "")' 2>/dev/null)"

if printf '%s' "$file_path" | grep -Eq '/\.mathem-matchning/omgang-[12]/(batch-[0-9]+|granskning)\.json$'; then
  exit 0
fi

echo "Blockerat: Mathem-agenterna får bara skriva sin svarsfil (.mathem-matchning/omgang-1 eller omgang-2, batch-NN.json eller granskning.json). Sökvägen '${file_path}' är inte en svarsfil — skriv till sökvägen på raden Svarsfil: i prompten." >&2
exit 2
