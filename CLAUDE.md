# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository. `AGENTS.md` is a symlink to this file, so other coding agents read the same
instructions — edit this file, not the symlink. Likewise `.agents/skills` is a symlink to
`.claude/skills`.

## Project Overview

This is a meal planning repository that implements a HelloFresh-like workflow for Swedish households. The system uses **multi-agent orchestration** to help with weekly meal planning through a structured 5-phase process: brainstorming → recipe selection → shopping list generation → recipe compilation → meal prep planning.

## Repository Structure

```
recipe/                              # Committed recipe library (not week-specific)
└── recept-<slug>-<portioner>p.md

YYYY-MM-DD/                          # Date-based meal planning folders (gitignored)
├── 01-brainstorming.md              # Meal preferences + candidate meals
├── 02-receptval.md                  # Selected recipes with links/sources
├── recept-*.md                      # Week-specific custom recipes
├── 03-handlingslista.md             # Pooled shopping list (generated on request)
├── 04-alla-recept.md                # All recipes in standardized format (generated on request)
├── 05-meal-prep-plan.md             # Optimized prep timeline (generated on request)
├── 06-mathem-plan.json              # Mathem cart plan (mathem-cart plan, experimental)
├── 06-mathem-varukorg.md            # Human-readable cart report (mathem-cart)
├── 06-mathem-kandidater.json        # Candidates for the matcher agents (mathem-cart, no prices)
├── .mathem-matchning/               # Per-part candidate files + matcher answers per round (mathem-cart)
└── .mathem-cache/                   # Mathem search cache, 24 h (mathem-cart)

meal-prep.example.yaml               # Household profile template + defaults (committed)
meal-prep.local.yaml                 # The user's own profile, written by /setup (gitignored)
.env.example                         # Template for .env (Mathem credentials; .env is gitignored)

docs/design/                         # Design notes for the Mathem integration

tools/mathem_cart/                   # Experimental Python CLI: shopping list → Mathem cart
├── README.md                        # Commands, .env variables, safety list
├── mathem-regler.yaml               # Committed rules (categories, limits, thresholds)
├── mathem-pins.example.yaml         # Pin file format; the user's pins go in mathem-pins.local.yaml (gitignored)
├── mathem_cart/                     # Package: parser, planner, applier, Mathem client
└── tests/                           # pytest (offline, httpx.MockTransport)

.claude/
├── rules/                           # Path-scoped conventions (load with matching files)
│   ├── recipe-style.md              # THE recipe standard — enforced by hook
│   └── recipe-examples.md           # Few-shot: gold recipe + good/bad pairs
├── hooks/
│   ├── validate_recipe.py           # Normalizes + validates a recipe file
│   ├── validate_week.py             # Cross-checks 03 shopping list against 04
│   ├── recipe_guard.sh              # PostToolUse wrapper
│   ├── subagent_recipe_gate.sh      # SubagentStop wrapper
│   ├── test_validate.py             # Regression test for the recipe validator
│   ├── first_run_nudge.sh           # SessionStart: suggests /setup when no profile exists
│   └── mathem_answer_guard.sh       # PreToolUse (Write) in the Mathem agents: answer file only
├── settings.json                    # Hook registration + permissions: ask before apply, deny .env (committed)
├── agents/
│   ├── meal-planning-orchestrator.md  # Top-level orchestrator (use with claude --agent)
│   ├── brainstorming-agent.md         # Phase 1: meal candidate generation
│   ├── recipe-researcher.md           # Phase 2: parallel recipe research (one per dish)
│   ├── recipe-creator.md              # Phase 2: custom recipe creation
│   ├── shopping-list-generator.md     # Phase 3: pooled shopping list
│   ├── recipe-compiler.md             # Phase 4: standardized recipe compilation
│   ├── meal-prep-optimizer.md         # Phase 5: time-optimized prep plan
│   ├── mathem-matcher.md              # Phase 6: judges one batch of Mathem candidates (haiku)
│   └── mathem-granskare.md            # Phase 6: second opinion on unsure items (sonnet)
├── skills/
│   ├── setup/                         # /setup: household profile + optional integrations
│   │   └── SKILL.md
│   ├── meal-planning-hello-fresh/     # Main workflow skill
│   │   ├── SKILL.md                   # Orchestration instructions
│   │   ├── reference.md               # Sources, units, categories
│   │   └── examples.md                # Output format examples
│   ├── create-recipe/                 # Custom recipe skill
│   │   └── SKILL.md                   # /create-recipe command
│   ├── export-to-notion/              # Notion export skill (optional, off by default)
│   │   └── SKILL.md                   # /export-to-notion command
│   ├── mathem-cart/                   # Mathem cart skill (optional, off by default, experimental)
│   │   ├── SKILL.md                   # /mathem-cart command
│   │   └── felsokning.md              # Troubleshooting table, read on unexpected exit codes
│   ├── verify-recipes/                # Recipe standard + shopping-list check
│   │   └── SKILL.md                   # /verify-recipes command
│   └── no-ai-slop/                    # Prose editor for recipe intros + Notion text
│       ├── SKILL.md                   # Vendored from the author's skills collection
│       └── eval.md                    # Self-check run after each edit
└── settings.local.json                # Local permission settings (gitignored)
```

## Household Profile (config)

User-specific settings live in `meal-prep.local.yaml` (gitignored, written by the `/setup`
skill). Missing keys fall back to the committed `meal-prep.example.yaml`, which also
documents every key. A user's explicit instruction in the conversation overrides both.

- Read the profile before Phase 1 and pass the relevant values (portions, allergies,
  equipment) to each subagent in its task — the rules for each key are in
  `## Hushållsprofil` in `.claude/skills/meal-planning-hello-fresh/reference.md`.
- `diet.allergies` are hard constraints for every agent.
- `integrations.<name>.enabled` decides which optional steps are offered. Everything
  is off by default.
- Never commit `meal-prep.local.yaml`, `.env` or anything in a week folder, and never put
  a user's IDs, names or preferences into committed files. If the profile is missing,
  suggest `/setup` once (a SessionStart hook also does this), then continue with the
  template's defaults if the user prefers.

## Multi-Agent Architecture

```
User
  ↓
[Main Conversation / Orchestrator]
  ├── Phase 1: brainstorming-agent (sonnet)
  ├── Phase 2: recipe-researcher × N (sonnet, PARALLEL — one per dish)
  │            + recipe-creator (on demand)
  ├── Phase 3: shopping-list-generator (sonnet)
  ├── Phase 4: recipe-compiler (sonnet)
  ├── Phase 5: meal-prep-optimizer (inherit)
  ├── (optional, off by default) export-to-notion
  └── (optional, off by default, experimental) mathem-cart — Python CLI + mathem-matcher × N (haiku, PARALLEL) + mathem-granskare (sonnet)
```

### Key Design Decisions

- **Parallel recipe research**: Phase 2 spawns one `recipe-researcher` agent per dish, all running in parallel. Each researcher compares 3-5 sources independently.
- **Subagents can't spawn subagents**: The main conversation acts as orchestrator. Alternatively, use `claude --agent meal-planning-orchestrator` for automated orchestration.
- **Orchestrator loads its skill explicitly**: `meal-planning-orchestrator` invokes `meal-planning-hello-fresh` with the Skill tool as its first action. It can't rely on the agent `skills:` field, because that field only preloads into agents spawned as subagents and is ignored when an agent runs as the main session via `claude --agent` (verified on Claude Code 2.1.284). Use `skills:` only on agents that are spawned as subagents.

## Recipe Standard: Rules + Hooks (deterministic)

Recipe formatting is **not** left to prompt adherence. The convention lives in one
place and is enforced mechanically:

| Layer | File | What it does |
|---|---|---|
| Convention | `.claude/rules/recipe-style.md` | The recipe standard. Path-scoped — loads only when working with recipe files. |
| Few-shot | `.claude/rules/recipe-examples.md` | Two gold recipes (one-session and two-day) + good/bad pairs with reasoning. |
| Enforcement | `.claude/hooks/recipe_guard.sh` (PostToolUse on `Write`/`Edit`/`MultiEdit`) | Normalizes mechanical issues in place, feeds remaining errors back to Claude. |
| Gate | `.claude/hooks/subagent_recipe_gate.sh` (SubagentStop) | `recipe-creator` / `recipe-compiler` can't finish while their recipes have errors. Releases after 2 blocked attempts so it can't loop. |
| Cross-check | `.claude/hooks/validate_week.py` | Every ingredient in `04` must appear in `03` with sufficient quantity. |
| Manual + CI | `/verify-recipes`, `.github/workflows/recipe-lint.yml` | Same validator on demand and on PRs (changed files only). |

**The rule that matters most:** every instruction step repeats the amount inline
(`Häll **1,5 dl** mjölk över **1 dl** ströbröd`), because the reader is standing at
the stove and won't scroll back to the ingredient list.

**Its necessary companion (Regel 6):** the inline amount must be the one the reader
actually takes. A step that says "halve every quantity" and then bolds the totals
turns Regel 1 into a hazard — the bold number reads as "this goes in the bowl now".
Steps run in batches spell out the per-batch amount first, with the total as
reference. A recipe is read three times — when shopping (Regel 4a's totals table),
when planning (Regel 4b's day grouping, Regel 7's decisions-before-steps) and when
cooking — and the standard has to carry all three.

**Recipe intros go through `no-ai-slop` (Regel 4d).** The 1–2 sentence intro under the
H1 is edited with the `no-ai-slop` skill. It is preloaded into `recipe-creator` through
its `skills:` field and invoked directly in the main conversation. It covers the intro
only; amounts and steps stay governed by the rules above.

When the hook reports `RÄTTAT`, the file on disk was already changed — re-read it
before editing further. `FEL` must be fixed, not explained away. `TIPS` is advisory.

Recipes in `recipe/` predate the standard and are not yet migrated; convert one only
when asked, rather than running a mass migration.

## Core Workflow & Architecture

### Phase-Gated Process (CRITICAL)

The workflow has **mandatory stop points** between phases. Never proceed to the next phase without explicit user approval:

1. **Phase 1 (Brainstorming)**: Generate meal candidates based on preferences
   - Stop and wait: User selects dishes or provides own recipes

2. **Phase 2 (Recipe Selection)**: Parallel recipe research + custom recipe creation
   - Stop and wait: Ask "Vill du att jag skapar handlingslista nu?"

3. **Phase 3 (Shopping List)**: Generate pooled, consolidated shopping list
   - Stop and wait: Ask "Vill du att jag skapar receptsamling och meal prep-plan nu?"

4. **Phase 4 (Recipe Compilation)**: Compile all recipes into standardized format (`04-alla-recept.md`)
   - No stop point — continues directly to Phase 5

5. **Phase 5 (Meal Prep)**: Create optimized preparation timeline
   - Then offer only the integrations enabled in the profile (see below); if none is enabled, finish without asking

### Optional integrations (off by default)

Enabled per user with `/setup notion` / `/setup mathem`, which set
`integrations.<name>.enabled: true` in `meal-prep.local.yaml`. After Phase 5, ask only
about the enabled ones, in this order, and run each in the **main conversation**
(Notion MCP isn't guaranteed in subagents; Mathem needs the user's explicit yes):

- **Notion** — "Vill du exportera veckan till Notion?" → `export-to-notion`
  (`/export-to-notion [YYYY-MM-DD]`). Publishes an overview page in the user's weeks
  database with the shopping list and meal-prep plan as the only two subpages, and links
  recipes in the user's recipe database. **Never duplicate a recipe**: match every dish
  against the recipe database first, create missing ones there, and write week-specific
  adaptations into the recipe page (ask first if the change alters the dish's
  character). Database IDs come only from `integrations.notion.*` in the profile. Prose
  written for Notion goes through `no-ai-slop`; content copied from `03`/`04`/`05` is
  published as is. Full procedure: `.claude/skills/export-to-notion/SKILL.md`.
- **Mathem** (experimental, unofficial) — "Vill du att jag fyller varukorgen på Mathem
  (experimentellt)?" → `mathem-cart` (`/mathem-cart [YYYY-MM-DD]`). Turns
  `03-handlingslista.md` into a filled cart via the Python CLI in `tools/mathem_cart/`.
  - **Never orders** — no checkout, delivery slot or order. The user checks the cart and orders in the Mathem app.
  - **Flow** (plan → matcher agents → `decide` → questions → `apply`): see `.claude/skills/mathem-cart/SKILL.md`. `apply` runs only on the user's explicit yes to the confirmation question in step 6 of that skill — subagents never run it.
  - **Credentials**: `MATHEM_EMAIL`, `MATHEM_PASSWORD`, `MATHEM_BOT_CONTACT` (the user's own contact) in `.env` — gitignored, never committed, never printed, never written by Claude.
  - Commands: `uv run --project tools/mathem_cart mathem-cart plan|decide|apply|pin|sök`.
  - Design: `docs/design/mathem-varukorg.md`, matching: `docs/design/mathem-matchning.md`; usage: `tools/mathem_cart/README.md`.

### Language & Units

- **Language**: Swedish only
- **Units**: Metric (g, kg, ml, dl, l, msk, tsk, st)
- **Normalization**: Convert to clearer units when appropriate (1000g → 1kg, 10dl → 1l)

### Recipe Sources Priority

**Prioritize QUALITY over convenience**, within the dish's level (see **Levels** below);
the tone follows `cook.experience` in the profile. A Vardag dish trades premium ingredients and time
for technique, never for blandness.

1. **Best quality sources** (Swedish or international):
   - Köket.se (high-quality Swedish recipes, chef-tested)
   - Arla (especially for dairy-based dishes)
   - Mitt Kök (authentic Nordic cuisine)
   - Tasteline (professional Swedish chefs)
   - Landleys Kök (high-quality home cooking)
   - International sources when authenticity matters (e.g., Asian cuisine from authentic sources)

2. **Secondary sources**:
   - ICA, Coop (good for basic recipes but not priority)
   - Food blogs (if quality is demonstrably high)

3. **Search strategy**:
   - Compare multiple sources for each recipe
   - Prioritize recipes with professional chef backgrounds
   - Look for techniques and flavor profiles that elevate the dish
   - Balance quality with weekday feasibility (not too advanced)

4. **Always provide clickable links**

### Default Parameters

Defaults come from the household profile (`meal-prep.example.yaml`: 4 portions per
recipe, dinner only, varied protein, oven + 4-ring stove). Language (Swedish) and units
(metric) are fixed product choices, not config.

- **Scaling**: Calculate ingredient scaling factors when portions differ from recipe

### Levels (Vardag / Standard / Avancerad)

Every dish has one of three levels, and Phase 1 asks for the week's mix every time
(suggest `level_mix` from the profile — default 3 Vardag + 1 Standard + 1 Avancerad —
if the user doesn't answer).

- **Vardag**: cheaper and quicker, max 30–45 min. Chicken, mince, pork, sausage, eggs,
  pulses and cheap fish are fine (kycklingfilé included); steaks and premium cuts
  (oxfilé, entrecote, lammracks, hälleflundra) are not. Its
  floor: every Vardag dish names a *lyft* (homemade sauce, quick pickle, toasted spices,
  hard sear, fresh acid/herb finish, crunchy topping) so cheap never means boring.
- **Standard**: today's default, 45–60 min.
- **Avancerad**: technique-heavy weekend projects, pricier ingredients allowed.

The definitions live in one place, `.claude/skills/meal-planning-hello-fresh/reference.md`
(`## Nivåer`). The brainstorming agent, recipe-researcher and recipe-creator read it
from there; edit that section, not the agents.

### Shopping List Generation (Phase 3)

- **Pool ingredients** across all selected recipes
- **Normalize units** for clarity
- **Use butiksvänliga names** (Swedish grocery store names)
- **Categorize**: Grönsaker, Frukt, Mejeri & Ägg, Kött & Fisk, Skafferi, Kryddor & Såser, Fryst, Bröd, Övrigt
- **Pantry assumptions**: List separately (salt, pepper, oils) - don't assume silently
- **Mark uncertainties**: Use "(verifiera)" instead of guessing

### Custom Recipes

When creating custom recipes, save as `YYYY-MM-DD/recept-<slug>-<portioner>p.md` and reference from `02-receptval.md` as "Eget recept: `recept-<slug>.md`". Use `/create-recipe` or the `recipe-creator` agent. The format is defined by `.claude/rules/recipe-style.md` and enforced by the recipe hook — see **Recipe Standard: Rules + Hooks** above.

### Meal Prep Planning (Phase 5)

Optimize for minimal total time by:
- Grouping similar tasks (chop all vegetables at once, cook all rice together)
- Parallelizing independent tasks (oven + stovetop + cold prep)
- Reusing bases/sauces when appropriate without sacrificing variety

## Specialized Agents

| Agent | Phase | Model | Purpose | Parallel? |
|---|---|---|---|---|
| `brainstorming-agent` | 1 | sonnet | Generate 10-20 meal candidates | No |
| `recipe-researcher` | 2 | sonnet | Find best recipe for ONE dish | **Yes — one per dish** |
| `recipe-creator` | 2 | inherit | Write custom recipe from scratch | Per recipe |
| `shopping-list-generator` | 3 | sonnet | Pool ingredients into shopping list | No |
| `recipe-compiler` | 4 | sonnet | Compile all recipes into standardized format | No |
| `meal-prep-optimizer` | 5 | inherit | Create time-optimized prep plan | No |
| `meal-planning-orchestrator` | All | inherit | Coordinate entire workflow | Top-level only |
| `mathem-matcher` | 6 | haiku | Judge one batch of Mathem candidates (no prices) | **Yes — one per batch** |
| `mathem-granskare` | 6 | sonnet | Second opinion on items the matcher was unsure about | No |

## Skills

| Skill | Invocation | Purpose |
|---|---|---|
| `setup` | `/setup [notion \| mathem \| visa]` | Create or change the household profile; enable optional integrations |
| `meal-planning-hello-fresh` | Auto or `/meal-planning-hello-fresh` | Main workflow with orchestration |
| `create-recipe` | `/create-recipe [dish] [portions]` | Create a custom recipe |
| `verify-recipes` | `/verify-recipes [YYYY-MM-DD]` | Check recipes against the standard and the shopping list against `04` |
| `export-to-notion` | `/export-to-notion [YYYY-MM-DD]` | Optional: publish a finished week to Notion as overview + subpages |
| `mathem-cart` | `/mathem-cart [YYYY-MM-DD]` | Optional: fill the Mathem cart from the shopping list (experimental; never orders) |
| `no-ai-slop` | `/no-ai-slop` or preloaded | Edit recipe intros and Notion prose so they don't read as AI. Vendored from the author's skills collection; keep local edits small so it can be re-synced |

## Working with Date Folders

When starting a new week:
1. Create folder: `YYYY-MM-DD/` (use the Monday of that week)
2. Start with Phase 1 brainstorming
3. Follow the phase-gated workflow strictly
4. Reference previous weeks' folders for inspiration but start fresh each time
