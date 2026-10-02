# Mathem-varukorg — matchning med Claude-agenter i stället för Laya

**Status:** approved 2026-09-24; implemented in tools/mathem_cart/ and .claude/agents/ (see §15 for deviations)
**Supersedes:** decision D2 (Laya) and the matching parts of §6 in
`docs/design/mathem-varukorg.md` ("the base spec"). Everything
else in the base spec — placement, credentials, category rules, quantity maths, the empty-cart
rule, safety (§8), `apply` — is unchanged.

## 1. Goal and success criteria

Decide which Mathem product is the right one for each shopping-list item with Claude agents
running inside Claude Code, so that the user is only asked about items that are genuinely
ambiguous. Code keeps owning search, rules, prices, quantities, validation and the cart.

Success, measured on the real list for week 2026-09-28 (68 items, see §3):

1. **≥ 90 %** of the products the models approve automatically are right, judged by the user
   on an evaluation sheet (§12).
2. **No** unrequested variant (lactose-free, light, vegan substitute, flavoured, ready-made,
   wrong form) is accepted without a question.
3. Every model answer is validated in code; a malformed or out-of-contract answer can only
   make an item undecided, never put a wrong product in the plan.
4. The loop between CLI and agents is bounded in code (at most two matching rounds).
5. The CLI still works without Claude Code: unpinned items simply end up undecided.

## 2. Decisions made during brainstorming

| # | Question | Decision |
|---|---|---|
| M1 | Where Claude runs | **Inside Claude Code.** The `/mathem-cart` skill dispatches subagents; the CLI never calls a model and needs no API key. A CLI-calls-the-API mode is out of scope (possible later). |
| M2 | Autonomy | Confident picks (`vald`) go straight into the plan; `osäker` gets one Sonnet review, and whatever is still unsure or unmatched becomes a question. The existing "Vill du att jag lägger allt i varukorgen på Mathem nu?" gate and the report remain the batch check. |
| M3 | Pins | The user's own answers are saved as pins (as today). Model picks are **never** saved as pins, so pins stay the user's ground truth. Pins decide before any model. |
| M4 | No candidate fits | The model may propose **one** new search term per item — broader ("tomat") or narrower ("plommontomater"). The CLI searches again and a second round judges the new candidates. Still nothing → question. The term is kept for that week only. |
| M5 | What is "right" | The same product as the list, with no unrequested variants; the list's qualifiers are requirements; organic, brand and package size are free — approve every acceptable candidate and let code pick the price (lowest total cost; storpack items by jämförpris, base spec §7). (Full text in §6.3.) |
| M6 | Structure | Two-pass CLI (`plan` gathers facts, `decide` validates and decides) with **batched** matcher agents in between (≈ 12 items per batch, in parallel). |
| M7 | Models | `mathem-matcher` on **Haiku** (classification against explicit rules); `mathem-granskare` on **Sonnet** for `osäker` items. No Opus inside the pipeline. |
| M8 | Laya | **Removed completely**: `matcher.py`, the `laya` extra, `eval`, the laya tests, `matchning.läge` / `matchning.tröskel`, and the "lär" mode. |

## 3. Evidence behind the change

Live run on 2026-09-24 against the real list for week 2026-09-28 (68 items, filtered by the
committed rules). Share of items where a relevant product (name contains the item) is among
the candidates shown:

| Ordering | Top 3 | Top 5 |
|---|---|---|
| Laya (zero-shot, `laya-multilingual`) | 47/68 (69 %) | 53/68 (77 %) |
| Mathem's own search order | 59/68 (86 %) | 61/68 (89 %) |
| Jämförpris | — | 40/68 (58 %) |

Laya scored irrelevant products ≈ 1.0 (Oatly iMat Visp first for vispgrädde, Högrevskorv first
for högrev, a beer for koriander) and followed labels rather than products (Garant Vispgrädde:
0.53 with "Från Sverige", 0.21 without). Only 2 of 68 items (perillablad, senapspulver) had no
relevant product anywhere in Mathem's results.

## 4. Architecture

```
03-handlingslista.md
  │ mathem-cart plan <vecka>
  │   parse → search → rule filter → pins
  │   · items settled by a pin → decided directly
  │   · the rest → 06-mathem-kandidater.json (round 1, batches ≤ 12 items, no prices)
  │   exit 4 = "matchning behövs"
  ▼
/mathem-cart skill (main conversation)
  │   one mathem-matcher (haiku) per batch, in parallel
  │   (+ one mathem-granskare (sonnet) when the candidate file has a review part)
  │   each writes one answer file under <vecka>/.mathem-matchning/
  ▼
  │ mathem-cart decide <vecka>
  │   validate answers (§7) → decide in code
  │   · vald → approved set → quantity maths → plan line (källa: haiku/sonnet)
  │   · ingen_passar + ny_sökterm (round 1 only) → new live search → round 2 batch
  │   · osäker (round 1) → review part for mathem-granskare in round 2
  │   · round-2 osäker / ingen_passar → undecided
  │   exit 4 when round 2 is needed; otherwise writes plan + report, exit 0 or 2
  ▼
06-mathem-plan.json + 06-mathem-varukorg.md
  │ undecided → questions to the user (skill) → `pin` → decide again (reuses stored answers)
  ▼
apply (unchanged)
```

### Units

| Unit | Change |
|---|---|
| `candidates.py` (new) | Build the candidate file: batching, `vara_id`, `kandidat_id` hash, candidate cap, **no price keys** |
| `answers.py` (new) | Load and validate answer files against the schema and the candidate file (§7); pure |
| `decider.py` (new) | Round state machine: turns validated answers + pins into plan lines, round-2 work or undecided items |
| `planner.py` | Stops at candidates: parse, search, filter, pins; no matcher, no asking |
| `cli.py` | `plan` → exit 4 when matching is needed; new `decide`; `eval` removed |
| `report.py` | "Beslut" column (`pin` / `fast` / `haiku` / `sonnet`) and the model's reason |
| `matcher.py` | **Deleted** |
| `.claude/agents/mathem-matcher.md`, `.claude/agents/mathem-granskare.md` (new) | Agent definitions with the requirements verbatim |
| `.claude/skills/mathem-cart/SKILL.md` | New matching loop (§9) |

Asking moves out of `plan`: `decide` asks the remaining undecided items interactively when
stdin is a TTY and `--no-input` is not given (same keys as today's `TerminalAsker`).

## 5. Candidate file `06-mathem-kandidater.json`

```json
{
  "kandidat_id": "3f9a1c0e7b2d",
  "vecka": "2026-09-28",
  "omgång": 1,
  "skapad": "2026-09-24T21:10:00+02:00",
  "batcher": [
    {"batch": 1, "svarsfil": ".mathem-matchning/omgang-1/batch-01.json",
     "varor": [
       {"vara_id": "v34", "vara": "Högrev", "behov": "1,8 kg", "kategori": "Kött & Fisk",
        "anteckning": "i bit; Galbi-jjim, sön 4/10; frys vid leverans",
        "kandidater": [
          {"produkt_id": 2737, "namn": "Scan Högrev Bit", "förpackning": "ca 1200 g",
           "märkning": ["Kött från Sverige"]}
        ]}
     ]}
  ],
  "granskning": null
}
```

- `vara_id` = `v` + the item's 1-based position in the shopping list, zero-padded to two
  digits; stable across rounds.
- `kandidat_id` = first 12 hex chars of SHA-256 over the canonical JSON of `vecka`, `omgång`,
  `batcher` and `granskning`. Answers must repeat it.
- Candidates per item: after the category rules, in **Mathem's search order**, at most 15 (2026-10-01: plus up to 5 more with the lowest
  jämförpris from the rest, moved up by `planner.agent_order` so the file stays price-blind)
  (the evidence in §3 shows nothing relevant beyond that). Dropped counts are logged.
- **Never** contains `gross_price`, unit price, promotions or discounts (tested).
- Round 2 contains only the items that need it: `batcher` for items with a new search term
  (their new candidates), and `granskning` for round-1 `osäker` items:

```json
"granskning": {"svarsfil": ".mathem-matchning/omgang-2/granskning.json",
  "varor": [{"vara_id": "v12", "vara": "…", "behov": "…", "kategori": "…", "anteckning": "…",
             "kandidater": [ … ],
             "tidigare": {"beslut": "osäker", "godkända": [4852], "motivering": "…"}}]}
```

## 6. Agents

### 6.1 Definitions

| File | `model` | `tools` | Job |
|---|---|---|---|
| `.claude/agents/mathem-matcher.md` | `haiku` | `Read, Write` | Judge one batch |
| `.claude/agents/mathem-granskare.md` | `sonnet` | `Read, Write` | Second opinion on the review part |

Both are dispatched by the skill with a prompt that names only: the candidate file path, the
batch number (or "granskning"), and the answer file path. They read the candidate file, write
exactly one answer file, and return a one-line summary.

### 6.2 Answer file

```json
{"kandidat_id": "3f9a1c0e7b2d", "omgång": 1, "batch": 1,
 "svar": [
   {"vara_id": "v34", "beslut": "vald", "godkända": [2737],
    "motivering": "Scan Högrev Bit — hel bit som listan kräver", "ny_sökterm": null}
 ]}
```

`beslut` ∈ {`vald`, `osäker`, `ingen_passar`}. `godkända` lists every acceptable product id.
`motivering` ≤ 160 characters. `ny_sökterm` is a string only with `ingen_passar` in round 1,
otherwise `null`. The reviewer writes `"batch": "granskning"` and may not set `ny_sökterm`.

### 6.3 Requirements (written verbatim, in Swedish, into both agent files)

1. Rätt vara är samma vara som på listan. **Inga varianter som listan inte ber om:**
   laktosfri, lätt, vegansk ersättning, smaksatt eller kryddad, färdigrätt, eller fel form
   (burgare är inte "högrev i bit", pulver är inte "vitlök").
2. Listans preciseringar är krav: "i bit", "benfri utan skinn", "lagrad, i block", "15 %".
3. Eko, märke och förpackningsstorlek är fria val. **Godkänn alla kandidater som duger** —
   koden väljer pris och storlek (storpack efter jämförpris för det som håller sig).
4. `vald` = minst en kandidat är tydligt rätt. `osäker` = en kandidat är rimlig men en
   precisering är oklar. `ingen_passar` = ingen duger; föreslå då en ny sökterm (bredare eller
   smalare) om en sådan sannolikt hjälper.
5. Använd bara id:n från varans egen kandidatlista. Svara på varje vara i batchen exakt en
   gång. Gissa aldrig om pris — du ser inga priser.

The reviewer additionally: sees `tidigare` (Haiku's verdict and reason); may set `vald` or
`ingen_passar`, or keep `osäker` (→ question to the user); never proposes a search term.

## 7. Validation in `decide` (structural error handling)

`decide` treats every answer file as untrusted input.

| Problem | Handling |
|---|---|
| Answer file for a batch is missing | Skill re-dispatches that batch once. Still missing → its items undecided, reason `matchning saknas` |
| Invalid JSON or schema violation | Skill re-dispatches once with the validation error in the prompt. Then undecided, reason `ogiltigt svar` |
| `kandidat_id` or `omgång` does not match the current candidate file | Answer ignored (treated as missing) |
| An item is unanswered, or answered twice | That item undecided (`besvarades inte` / `dubbelt svar`); the rest of the batch is used |
| An answer for a `vara_id` not in the batch | Ignored, with a warning |
| A product id not among that item's candidates | Id dropped with a warning; nothing left → treated as `osäker` |
| `vald` with empty `godkända` | Treated as `osäker` |
| An approved product fails the category rules or availability on re-check | Dropped; nothing left → `osäker` |
| `ny_sökterm` outside round 1, with a verdict other than `ingen_passar`, empty, or equal to a term already searched | Ignored → the item is undecided |
| A third round would be needed | Refused; everything unresolved becomes undecided |
| Quantity cannot be computed | Undecided with the quantity reason (as today) |

`decide` reads nothing outside `<vecka>/06-mathem-kandidater.json` and
`<vecka>/.mathem-matchning/`. It prints, per run: counts per source (`pin`, `fast`, `haiku`,
`sonnet`), counts per undecided reason, and every warning.

State: `decide` writes the candidate file for round 2 (overwriting round 1's, with a new
`kandidat_id`) and keeps all answer files. Re-running `decide` after new pins re-derives the
plan from the stored answers of the latest round without new model calls; pins override
model decisions.

## 8. CLI

| Command | Change |
|---|---|
| `plan [vecka] [--hoppa VARA]…` | Parse, search, filter, pins. Writes the candidate file (round 1) and exits **4** when any item needs matching; otherwise writes plan + report (exit 0 or 2). `--no-input` is accepted and ignored (kept for scripts). |
| `decide [vecka] [--no-input] [--hoppa VARA]…` | New. §7. Exit **4** when round 2 is needed; else writes plan + report and exits 0/2; asks remaining items interactively on a TTY. |
| `apply`, `pin`, `sök` | Unchanged. |
| `eval` | Removed. |

Exit codes: `0` ok, `1` error, `2` plan has undecided items, `3` safety abort,
**`4` matchning behövs** (agents must answer the candidate file, then run `decide`).

`mathem-regler.yaml`: `matchning.läge` and `matchning.tröskel` are removed; an old file that
still has them loads with one warning.

## 9. Skill `/mathem-cart` (main conversation)

1–2. As today (week folder, `.env` presence check).
3. `mathem-cart plan <vecka> --no-input [--hoppa …]`. Exit 0/2 → step 6; 4 → step 4.
4. **Matching loop** (at most two passes, enforced by `decide`):
   - Read `06-mathem-kandidater.json`. Dispatch one `mathem-matcher` per entry in `batcher`
     and, if `granskning` is present, one `mathem-granskare` — all in the same message, in
     the background. Each prompt names the candidate file, the batch (or `granskning`) and
     its `svarsfil`.
   - When all have returned: `mathem-cart decide <vecka> --no-input`. If it reports a missing
     or invalid answer file, re-dispatch that batch once with the reported error. Exit 4 →
     repeat step 4 for round 2. Exit 0/2 → step 5.
5. Undecided items → `AskUserQuestion` as today (top 3 candidates + "Hoppa över"; "Other" =
   new search term). Save with `pin`; re-run `decide`.
6. Show the summary incl. counts per source and the model reasons for flagged lines, then the
   existing question **"Vill du att jag lägger allt i varukorgen på Mathem nu?"**.
7–8. `apply` and verification, unchanged.

## 10. Report

- The cart table gains a **Beslut** column (`pin`, `fast`, `haiku`, `sonnet`) and a
  **Motivering** column (the model's reason, ≤ 80 characters shown; empty for pins).
- The header line shows counts per source.
- "Behöver beslut" shows candidates in Mathem's search order with the undecided reason; the
  `p` value disappears.

## 11. Removal and migration

Delete `matcher.py`, `tests/test_matcher.py`, `tests/test_matcher_live.py`, the `laya` extra
in `pyproject.toml` (and re-lock), the `laya` pytest marker and conftest exemption, `eval`
and its tests, `matchning.läge` / `matchning.tröskel` from `mathem-regler.yaml`, and Laya
mentions in CLAUDE.md, the README and the skill. The base spec's D2 row points to this spec.

## 12. Testing and live evaluation

Unit tests (no network, no models):
- `answers.py`: one test per row of §7, from hand-written answer files.
- `candidates.py`: batch size ≤ 12, stable `vara_id`, `kandidat_id` changes with content,
  cap of 20 (15 in search order + 5 by jämförpris), **no price or deal keys anywhere in the file**.
- `decider.py`: round 1 → round 2 → final; a third round refused; pins override stored
  answers; model picks never written to `mathem-pins.yaml`.
- Report: Beslut and Motivering columns, counts per source.
- Static test of the agent files: frontmatter `model: haiku` / `model: sonnet`,
  `tools: Read, Write` only, and the §6.3 requirement text present.
- CLI: exit 4 path, `decide` without answer files → undecided `matchning saknas`, exit codes.

Live evaluation (once, after implementation), on `2026-09-28/03-handlingslista.md`:
- Run the full skill flow with real agents (search only; never `apply`, never log in).
- Produce `2026-09-28/06-mathem-utvardering.md` (gitignored week folder): one row per item —
  item, need, source, chosen product, all approved products, reason, and an empty
  "Rätt? (ja/nej)" column for the user.
- Report: counts per source and per undecided reason, number of items resolved by the second
  round, and top-3 relevance (§3 heuristic) of the model's first approved product versus
  Mathem's own order.

## 13. Out of scope

A CLI mode that calls the Anthropic API directly; changes to `apply`, the safety rules, the
quantity maths or the category rules; brand or organic preferences (M5 keeps them free).

## 14. Open items to verify during implementation

1. Whether a Claude Code session registers agent definitions created during that session; if
   not, the live evaluation dispatches them in a fresh session (or emulates them with the same
   model and the agent file body as prompt, and says so).
2. Batch size: 12 is the starting point; adjust if Haiku drops items or exceeds output limits.
3. Haiku's accuracy on qualifiers ("i bit", "15 %") — the evaluation sheet decides whether
   more items should go to the reviewer.

## 15. Implementation notes (2026-09-24)

Deviations decided while planning and implementing.

| # | Deviation |
|---|---|
| K1 | §5 lists the item keys `vara_id vara behov kategori anteckning kandidater`; every item also carries `sökterm` (the term that was searched), because `decide` needs it for "equal to a term already searched" and round 2 — it is not a price — and `anteckning` is `""` when the list has none. |
| K2 | §4 sends "the rest → candidate file"; items whose quantity can't be parsed (`mängd saknas`, `okänd enhet`) are undecided in `plan` directly, because a model can't fix a missing amount. |
| K3 | Not in the spec: items with zero candidates after the rules are still sent, with `kandidater: []`, so the model can propose a search term (M4). |
| K4 | §7 says "`decide` reads nothing outside `06-mathem-kandidater.json` and `.mathem-matchning/`"; that holds for model output, but `decide` also reads the shopping list, the rules, the pins and the week's search cache, and searches live for round-2 terms. Answer files are read only at paths `decide` derives itself (`.mathem-matchning/omgang-N/batch-NN.json`, `granskning.json`), never from `svarsfil`. |
| K5 | §7 says `decide` "writes the candidate file for round 2 (overwriting round 1's)"; each round's file is also kept at `.mathem-matchning/omgang-N/kandidater.json` so re-runs can re-validate round-1 answers, and `06-mathem-kandidater.json` is always the current round. `decide` checks that each file's `kandidat_id` still matches its content (self-hash) and that `06` equals the current round's copy; otherwise exit 1 "kör plan igen". |
| K6 | §7 says "Skill re-dispatches … once. Still missing → undecided"; this is enforced in code. The first `decide` that finds missing or invalid answer files (when at least one of the round's answer files exists) exits 4 with `Skicka om:` lines and does not advance; the next `decide` makes those items undecided. When **no** answer file of the round exists (the CLI was run without Claude Code), the items become `matchning saknas` at once (success criterion 5). |
| K7 | §7 says "A product id not among that item's candidates → dropped"; an approved id must be in the item's list in the candidate file **and** in the current rule-filtered search for the same term, so an edited candidate file cannot add a product, and a product that sold out since `plan` is dropped. |
| K8 | §6.2 limits `motivering` to 160 characters; a longer reason is cut to 160 characters with a warning instead of failing the whole file. An answer wrapped in a ```` ``` ```` code fence or starting with a BOM is read, with a warning, and `ny_sökterm: ""` counts as `null`. |
| K9 | §7 says `ny_sökterm` misuse is "ignored → the item is undecided"; this is taken literally: a term with `vald`/`osäker`, in round 2, from the reviewer, or equal to the searched term makes that item undecided with reason `ogiltig sökterm`. |
| K10 | Refines §7: an answer's `batch` that doesn't match the part is a schema violation (`ogiltigt svar`, re-dispatched once with the error), not "ignored". |
| K11 | Not in the spec: `plan` removes the previous `06-mathem-kandidater.json` and `.mathem-matchning/` before it starts, and `plan` and `decide` delete an existing `06-mathem-plan.json` whenever they exit 4, so `apply` can never run a plan that predates the current matching. |
| K12 | Changes the base spec §9 plan JSON: `läge` is removed; lines and undecided items gain `motivering`; candidates lose `p`. |
| K13 | Refines §8 `decide`: `decide` without a candidate file works when nothing needs matching (everything is pinned or undecided for code reasons), so the skill can always re-run `decide` after pinning; with items that need matching it exits 1 "kör plan först". |
| K14 | Refines the §8 `mathem-regler.yaml` warning: `Rules.warnings` carries the one warning, and `plan`, `decide` and `apply` print it; old `läge`/`tröskel` values are no longer validated. |
| K15 | Not in the spec (found while removing `eval`): `cli.main` catches the `SystemExit` that argparse raises for a usage error or `--help` and returns its code (1 for an unknown subcommand such as `eval`, 0 for `--help`) instead of raising. The console script's exit codes are unchanged. |
| K16 | Refines K5 and K6 (found in review): agents can write any file under `.mathem-matchning/`, so `decide` trusts none that an agent could reset. The round-2 candidate file carries `svar_omgång_1`, a digest of the round-1 answer files it was built from (part of `kandidat_id`); if those files change afterwards, `decide` exits 1 "svaren i omgång 1 har ändrats … kör plan igen". `06-mathem-kandidater.json` claiming round 1 while `omgang-2/kandidater.json` exists is refused the same way ("omgång 2 finns redan"). `omsändning.json` is `{"delar": […], "kontroll": …}` with a check value over `kandidat_id` and the parts; a record that doesn't verify counts as every part already resent (warning), so K6's one resend per part holds. |
| K17 | Changes §5, §6.1 and §9 (found in review): a real week's candidate file (~250 KB) is too large for one Read. `write_round` also writes each part on its own to `.mathem-matchning/omgang-N/batch-NN-kandidater.json` / `granskning-kandidater.json` (`kandidat_id`, `vecka`, `omgång`, `batch`, `svarsfil`, `varor`), and `plan`/`decide` print one stdout line per part, `  batch N: <kandidatfil> → <svarsfil>`. The skill never reads `06-mathem-kandidater.json`; each agent's `Kandidatfil:` is its own part file, and the agent text says to page with `offset`/`limit` if Read still truncates. `plan` and round-2 `decide` log cut candidates (§5) as one warning line: the items with their counts when at most five were cut, otherwise the number of items and the total cut (the live run capped 64 of 68 items, and one line each drowned the output). |
| K18 | Changes §14 item 1 (found in review): the skill no longer falls back to a `general-purpose` agent when `mathem-matcher`/`mathem-granskare` are unknown, because that agent has more tools than `Read, Write` (§6.1) and could run the CLI, write pins or poison the search cache; the skill stops and asks for a new session instead. |
| K19 | Not in the spec (user decision 2026-09-30): alcohol is bought at Systembolaget, never on Mathem. `mathem-regler.yaml` has `köps_inte_på_mathem: {<place>: [words]}`; an item whose head noun — the last word before any comma, hyphens splitting words — is a listed word ("vin" matches "torrt vitt vin" and "vin, torrt vitt", not "sherry vinäger", "cider-vinäger", "risvinäger" or "matlagningsvin"; narrowed from any whole word after code review) is never searched or matched and is listed under "Ej med" as "<item> (köps på <place>)". `vara_id`s stay positional. Small qualifier misses such as 32 % for "34 %" are accepted by the user and left to the model. |
| K20 | Changes the quantity maths for items counted in pieces (base spec §7, found in the live run: 10 of 68 items undecided). A package sold by weight counts as `round(weight / piece weight)` pieces, at least one, so "Gurka, 270 g" is one cucumber and an avocado 2-pack of 325 g is two. `styckvikt_g` gained common produce (vitlök, ingefära, jalapeño, gurka, isbergssallad, morot, schalottenlök, avokado, lime, päron and more), and plurals in -ötter find their singular (morötter → morot). With a head weight for vitlök, 3 cloves buy one head (the Q1 case is now decided instead of undecided). |
| K21 | Changes the "annars X" rule added in review (AQ3): when only the note's fallback is among the candidates, the agent answers `vald` with the fallback, not `osäker` — the list already said the fallback is fine. When the item itself is among the candidates, only the item is approved, as before. |
| K22 | Not in the spec, recorded after code review: the shopping-list parser also reads table rows and name-first lines, the units `kruka flaska limpa påse tub`, and aliases (`hela`/`stjälk` → `st`); headings with "kontrollera hemma"/"köp inte" count as excluded sections (listed under "Ej med"); commentary sections ("Att verifiera", "Noteringar", "Kostnad" …) are ignored entirely, because their bullets are notes, not items. The CLI also takes `--root`/`MATHEM_CART_ROOT`, `--regler`, `--pins` and the alias `sok`; `plan` flags a line `för_många` before `apply` would abort on it; CI can be run by hand (`workflow_dispatch`). |

## 16. Live evaluation (2026-09-30, week 2026-09-28)

Run as §12 describes: `plan` → 6 `mathem-matcher` (haiku) in parallel → `decide` → round 2
(1 matcher batch, 1 `mathem-granskare`) → `decide`. Search only (cache expired, so live
search at ≤ 1 request/s); no login, no `apply`. Sheet for the user's marks:
`2026-09-28/06-mathem-utvardering.md`.

- §14 item 1: the agent types created during the implementing session were not available
  there. They were registered after the session restarted, and the run used them directly.
- All 7 answer files were valid on the first try; no re-dispatch.
- Round 1: 62 `vald`, 2 `osäker`, 4 `ingen_passar` (with a new search term).
- Round 2: 6 items. 3 resolved (2 by the matcher on a new term, 1 by the reviewer:
  daikon → rättika); 3 stayed undecided.
- Final plan: 55 lines (54 `haiku`, 1 `sonnet`). 13 undecided: 10
  `ingen förpackning går att räkna` (piece-counted produce such as gurka, lime, avokado,
  where the quantity maths can't convert `st`; a quantity issue, out of scope per §13),
  2 `ingen passar` (perillablad, kastanjer), 1 `osäker` (senapspulver, where the only
  candidate was dijonsenap).
- Top-3 relevance with the §3 heuristic (the product name contains the item): the model's
  first approved product is relevant for 45/68 items, Mathem's own top 3 for 49/68. The
  heuristic undercounts both (for example "Lök Röd" does not contain "rödlök") and ignores
  that code buys the cheapest approved product, not the first. The user's marks on the
  sheet decide success criterion 1.
- Spot check before marking: `Crème fraiche 34 %` got only 32 % products approved (a
  requirement-2 miss); `Ljus lager` resolved to a 0,5 % beer (a variant the list didn't
  ask for); `Torrt vitt vin` resolved to a matlagningsvin. These three are candidates for
  criterion 2 and for §14 item 3 (more items to the reviewer).

After K19–K21, `decide` was re-run on the stored answers (no new model calls): the 10
piece-counted items all resolved (2 gurkor, 6 avokado, 4 lime, 5 rödlök instead of 7), wine
and beer moved to "Ej med", and the plan has 63 lines (62 `haiku`, 1 `sonnet`).
3 items remain for the user: perillablad and kastanjer (not sold on Mathem), and senapspulver
(its stored answer predates K21; a new run approves the dijonsenap fallback).

