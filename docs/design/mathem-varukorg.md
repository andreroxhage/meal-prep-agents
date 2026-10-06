# Fas 6 (experimentell) — Mathem-varukorg

**Status:** approved 2026-09-24; implemented in `tools/mathem_cart/` (see §14 for deviations and §13 for the answers found during implementation)
**Scope:** one new, optional pipeline step plus a standalone command. Fills the user's
Mathem cart from a week's shopping list. **Never places an order** — checking the cart
and ordering is the user's responsibility.

## 1. Goal and success criteria

After Phase 5 and the optional Notion export, the user can run one more optional step
(or run it standalone on any week folder) that turns `03-handlingslista.md` into a filled
cart at mathem.se.

Success means:

1. The cart contains one line per shopping-list item that could be decided, with the right
   product and enough packages to cover the need.
2. Within the user's quality requirements, the cheapest total cost wins (deals included).
3. Nothing questionable lands in the cart silently: uncertain matches are asked about
   (interactive) or listed as "Behöver beslut" (non-interactive).
4. A report `06-mathem-varukorg.md` lets the user check every line in minutes.
5. No code path can place an order, choose a delivery slot or touch anything beyond
   search, product detail, login and the cart.

Out of scope: checkout, delivery slots, other stores, mixing package sizes within one
item, the in-browser Laya variant (possible later replacement for `apply`, see §11).

## 2. Decisions made during brainstorming

| # | Question | Decision |
|---|---|---|
| D1 | Placement | Very last optional step, after the Notion export. Must also run standalone. |
| D2 | Model | ~~Laya (open source, Apache 2.0, local). Not Jev (proprietary, hosted).~~ **Superseded 2026-09-24** by Claude agents inside Claude Code — see `2026-09-24-mathem-claude-matchning-design.md`. |
| D3 | Credentials | `MATHEM_EMAIL` / `MATHEM_PASSWORD` from a gitignored `.env`. Never committed, never logged. |
| D4 | Quality vs price | **Rules per category** (option B). Quality is expressed as requirements; within them the cheapest total wins. |
| D5 | Uncertain match | **Ask** (interactive), save the answer as a pin. Non-interactive fallback: leave out of the cart, list as "Behöver beslut". |
| D6 | Quantity | **Lowest total cost that covers the need, with an overshoot cap per category.** Freezable categories (meat, fish, pantry, frozen) have no cap — 2 × 700 g for a 1,2 kg need is fine. |
| D7 | Non-empty cart | **Refuse** to add anything if the cart is not empty. Re-runs are handled by the `plan`/`apply` split. |
| D8 | Architecture | Python CLI in the repo (`tools/mathem_cart/`) wrapped by a skill (`/mathem-cart`). |

## 3. Research facts this design relies on

Verified live on 2026-09-24 unless marked otherwise.

**Mathem search (no login):**
`GET https://www.mathem.se/api/v1/search/mixed/?q=<term>&type=product&page=<n>` returns
`items[]`; entries with `type == "product"` carry `attributes`, and entries with
`type == "product_list"` carry nested products (e.g. `prev_bought_products`). 30 per page,
`attributes.hasMoreItems` for paging. Product attribute keys seen:

```
id, full_name, brand, name, name_extra, gross_price, gross_unit_price,
unit_price_quantity_abbreviation, unit_price_quantity_name, client_classifiers,
promotion, promotions, discount, pills, bonus_info, availability, front_url,
absolute_url, currency, images, metadata
```

Examples:

| full_name | name_extra | gross_price | gross_unit_price | promotions[].title |
|---|---|---|---|---|
| Garant Vispgrädde 36% | `5 dl` | 27.20 | 54.40 / l | — |
| Garant Innerfilé av Svensk Kyckling Fryst | `700 g` | 60.95 | 87.07 / kg | — |
| Kronfågel Kycklinglårfilé Fryst | `Max 2 per kund, 700 g` | 72.50 | 103.57 / kg | `2 för 99 kr` |
| Reko Kycklingbröstfilé Fryst EKO/KRAV | `ca 430 g` | 150.77 | 350.63 / kg | `-10%` |

`client_classifiers[].name` carries labels like `Från Sverige`, `Lactose free`,
`Färskvarugaranti i 4 dagar`. Prices are strings.

**Mathem login and cart (from ha-mathem, MIT, github.com/marcusforsberg/ha-mathem — not
yet exercised by us):**
- Base `https://www.mathem.se/api/v1`, `origin`/`referer` `https://www.mathem.se/se/`.
- Login: `GET https://www.mathem.se/se/user/login/` (browser-style `Accept`) seeds the
  `csrftoken` cookie; then `POST /user/login/` with `{"username", "password"}` and header
  `x-csrftoken`. Success sets the `sessionid` cookie.
- Cart read: `GET /cart/?group-by=recipes`.
- Cart mutation: `POST /cart/items/?group-by=recipes` with
  `{"items": [{"productId": <int>, "quantity": <delta>}]}`. Quantities are **deltas**;
  the response is the full updated cart.
- ha-mathem refuses any URL containing `checkout/confirm`. We go further (§8).

**Mathem robots.txt:** asks automated clients to send a User-Agent containing `bot`, a
program name and contact info, and to back off on 429/5xx honouring `Retry-After`. Cart
endpoints are disallowed for crawlers. This tool is not a crawler (it acts on the user's
own account at low volume), but the API is unofficial and can change or break at any time.

**Laya (github.com/NandhaKishorM/laya, Apache 2.0):**
- `pip install laya`, Python ≥ 3.10. `from laya import Router`;
  `Router().predict(state, questions)` → `result["answers"][<key>]`.
- Question types: `choice` (≤ ~20 options), `score`, `noul` (yes/no, returns P(true)).
- Checkpoints: `laya` (ModernBERT-large, 421M, English, 512 tokens),
  `laya-multilingual` (mmBERT-base, 322M, 100+ languages incl. Swedish, 1 024 tokens),
  `laya-typed-decisions` (fine-tuned, 421M). The router sends non-English text to
  `laya-multilingual`.
- Runs on CPU, Apple Silicon (MPS) and GPU.
- **Known weaknesses (from its README):** base checkpoints are near random (0,36) on typed
  decisions zero-shot; only the fine-tuned checkpoint reaches 0,77. `noul` can follow
  option labels instead of the state. This is why §6 starts in learning mode.
- The Medium article on running Laya in the browser could not be fetched (HTTP 403) and
  is not relied on.

## 4. Architecture

```
03-handlingslista.md
  │ 1. parse       items: namn, mängd, enhet, kategori (from the ## heading)
  ▼
  │ 2. search      Mathem search API → up to 30 candidates per item (cached)
  ▼
  │ 3. filter      category rules from mathem-regler.yaml
  ▼
  │ 4. match       pins first; else Laya noul per candidate → P(acceptable)
  ▼
  │ 5. decide      accepted set per item, or "undecided" (ask / Behöver beslut)
  ▼
  │ 6. quantity    package size, total cost incl. deals, overshoot cap
  ▼
06-mathem-varukorg.md (report)  +  06-mathem-plan.json (input to apply)
  │
  │ apply: login → refuse if cart not empty → add lines → read cart back → compare
  ▼
Mathem cart → user checks and orders in the Mathem app
```

### Components

All code lives in `tools/mathem_cart/` (a uv project). Each unit has one job and can be
tested alone.

| Unit | Job | Depends on |
|---|---|---|
| `shopping_list.py` | Parse `03` into `Item`s; skip the Skafferi-antaganden and Specialingredienser sections | — |
| `mathem/session.py` | HTTP session: base URL, headers, CSRF, login, **endpoint allowlist**, rate limit, backoff | `httpx` |
| `mathem/products.py` | Search (paged, flattened, previously-bought first) and product detail | session |
| `mathem/cart.py` | Read cart, add by delta, `set_quantity` | session |
| `mathem/models.py` | `Product`, `Cart`, `CartLine` dataclasses from API JSON | — |
| `packaging.py` | Parse package size, quantity limit and deals from a `Product` | models |
| `units.py` | Convert amounts between units using the rule file's tables | rules |
| `rules.py` | Load `mathem-regler.yaml`; filter candidates per category | — |
| `pins.py` | Load/save `mathem-pins.yaml` | — |
| `matcher.py` | **Only** file importing `laya`. `score(item, candidates) → {product_id: p}` | laya (optional) |
| `quantity.py` | Pure: choose product + package count for an item | packaging, units, rules |
| `planner.py` | Orchestrates steps 1–6, writes the plan JSON and the report | all above |
| `applier.py` | Executes a plan against the cart and verifies it | cart |
| `report.py` | Renders `06-mathem-varukorg.md` from a plan (and apply result) | — |
| `cli.py` | `mathem-cart` entry point (§9) | planner, applier, pins |

The `mathem/` client is adapted from ha-mathem (MIT): rewritten sync with `httpx`, keeping
the MIT copyright notice in `tools/mathem_cart/mathem/LICENSE-ha-mathem` and a header
comment naming the source.

Committed config lives next to the code:
`tools/mathem_cart/mathem-regler.yaml`, `tools/mathem_cart/mathem-pins.yaml`.

Per-week output lives in the (gitignored) week folder:
`YYYY-MM-DD/06-mathem-varukorg.md`, `YYYY-MM-DD/06-mathem-plan.json`,
`YYYY-MM-DD/.mathem-cache/`.

## 5. Parsing the shopping list

`03-handlingslista.md` (format owned by `shopping-list-generator`) has `## <Kategori>`
headings with lines `- <mängd> <ingrediens>`, optionally `- [ ] …`, `(verifiera)` and
other parentheticals.

- Category = the nearest `##` heading. `## Skafferi-antaganden …` and
  `## Specialingredienser` are skipped and listed under "Ej med" in the report.
- Amount: decimal comma or point (`1,2`/`1.2`), fractions (`½`), ranges (`2–3` → upper
  bound). Units: `g kg ml cl dl l msk tsk krm st förp knippe burk paket`.
- Parentheticals are kept as `anteckning` and stripped from the search term.
  `(verifiera)` is kept as a flag and shown in the report.
- A line whose amount cannot be parsed becomes an item with `mängd = None`; it is always
  undecided.

## 6. Matching

### Candidate filter (code, before any model)

From `mathem-regler.yaml`, per category:

- `uteslut`: case-insensitive substrings; a candidate whose `full_name` or `name_extra`
  contains any of them is dropped.
- `kräv_någon_av`: list of alternatives like `märkning:Från Sverige` (matches
  `client_classifiers[].name`) or `namn:svensk` (matches `full_name`). At least one must hold.
- `föredra_någon_av` (added, §14 V20): same syntax, but a preference. If any remaining
  candidate satisfies it, only those are kept; if none does, all remaining candidates stay
  and a line decided from them is flagged `ej föredragen`.
- Unavailable products (per `availability`) are dropped.

### Pins

`mathem-pins.yaml`, keyed by the normalized ingredient name:

```yaml
vispgrädde:
  godkända: [6851, 2380]      # accepted products; cheapest available wins
kycklingfilé:
  sök: kycklingbröstfilé      # optional search-term override
  godkända: [12345]
krossade tomater:
  fast: 9876                  # always exactly this product
```

- `fast` set → that product if available, else undecided.
- `godkända` non-empty and ≥ 1 available → accepted set = available pinned products.
  Laya is not called.
- Otherwise → Laya / ask.

### Laya question

One `noul` per remaining candidate (batched per item):

```python
state = {"ingrediens": "vispgrädde", "behov": "3 dl", "kategori": "Mejeri & Ägg",
         "produkt": "Garant Vispgrädde 36%", "förpackning": "5 dl",
         "märkning": ["Från Sverige", "Färskvarugaranti i 4 dagar"]}
question = {"acceptabel": {"type": "noul",
            "instructions": "Är produkten rätt vara att köpa för ingrediensen i ett recept?"}}
```

Price and deals are **never** sent to the model; price is decided in code.

### Modes

`mathem-regler.yaml` → `matchning.läge`:

- `lär` (default): Laya only **orders** candidates. Every item without a usable pin is
  undecided and asked about. This is the mode until `eval` shows Laya can be trusted.
- `auto`: candidates with P ≥ `matchning.tröskel` (default 0,85) form the accepted set.
  If none reach it → undecided.

If `laya` is not installed or fails to load, the planner runs as `lär` with candidates
ordered by jämförpris and prints one warning.

### Asking

- **Interactive** (`stdin` is a TTY and no `--no-input`): per undecided item, show the
  5 most likely candidates (name, package, price, jämförpris, deal, P). Keys: `1–5` accept
  (adds to `godkända`), `f` + number pin as `fast`, `s` new search term (saved as `sök`),
  `h` skip this week. Answers are written to `mathem-pins.yaml` immediately.
- **Non-interactive:** undecided items and their top 5 candidates are written to
  `06-mathem-plan.json` (`undecided[]`) and listed as "Behöver beslut" in the report.
  The skill (§10) turns them into questions and calls `mathem-cart pin`.

## 7. Quantity calculation

### Package parsing (`packaging.py`)

From `name_extra`:
- Strip a `Max N per kund,` prefix → `max_antal = N`.
- `ca 430 g` → 430 g, flagged `ungefärlig`.
- `3x400 g` / `3 x 400 g` → 1 200 g; `6-pack` / `6 st` → 6 st.
- Units `g kg ml cl dl l st`.
- Cross-check / fallback: when `unit_price_quantity_abbreviation` is `kg` or `l` and both
  prices exist, `gross_price / gross_unit_price` gives the package size. Disagreement over
  5 % → flag.
- Unparseable and no fallback → the product is unusable for calculation; if no candidate
  is usable the item is undecided.

### Deals

From `promotions[].title`:
- `N för X kr` → buying in groups of N costs X.
- `-P%` → needs verification during implementation: whether `gross_price` already
  includes it (compare against the `discount` field). Until verified, not applied.
- `Prismatch` and anything unrecognized → not applied, shown in the report.

### Unit conversion (`units.py`)

`1 msk = 15 ml`, `1 tsk = 5 ml`, `1 krm = 1 ml`, `1 dl = 100 ml`, `1 cl = 10 ml`.
Across mass/volume/count via `omräkning.densitet_g_per_dl` and `omräkning.styckvikt_g`.
Items measured in `msk`/`tsk`/`krm` whose product is a spice/sauce jar → 1 package.
No conversion path → undecided.

### Choice (`quantity.py`, pure)

For each product in the accepted set:
1. `n = ceil(need / package_size)`, respecting `max_antal`.
2. `cost` = sum with multibuy deals applied.
3. `överköp = (n × size − need) / need`.
4. Drop if `överköp > max_överköp` for the category, unless the category is `frysbar`.

**Storpack** (2026-10-01): for an item in a `storpack: ja` category or whose head noun is in
`storpack_varor`, step 4 is skipped and the pick is the lowest effective jämförpris
(`cost / amount bought`, so multibuy deals count) among options whose cost is at most the
cheapest option's cost + min(`storpack_max_merkostnad` × cost, `storpack_max_merkostnad_kr`).
Tie → lower cost → smaller overshoot. The line is flagged `storpack` when it isn't the cheapest.

**Basvaror** (2026-10-06): cheap staples (potatoes, rice, pasta …) whose head noun is in
`basvaror.varor`. Same pick as storpack, with three differences: the allowance is
`basvaror.max_merkostnad_kr` alone (a share of a 20 kr bag never admits a 5 kg sack, which is
how small packs ended up in the cart); the pick must lower the effective jämförpris by at
least `basvaror.min_besparing` compared with the cheapest option, else the cheapest stays;
and an optional per-item max amount (`potatis: 5 kg`) drops options that buy more in total,
except the cheapest. Basvaror go before `storpack_varor` and the category's `storpack`.

Otherwise: pick the lowest `cost`; tie → lower jämförpris → smaller overshoot. If every option exceeds
the cap, pick the smallest overshoot and flag `överköp`. One product type per item.

### Rule file (`mathem-regler.yaml`)

```yaml
matchning:
  läge: lär            # lär | auto
  tröskel: 0.85
säkerhet:
  max_total_kr: 3000
  max_antal_per_rad: 10
  plan_max_ålder_h: 24
standard:
  max_överköp: 0.25
kategorier:
  Kött & Fisk:
    frysbar: ja
    föredra_någon_av: ["märkning:Från Sverige", "märkning:Svensk Fågel", "märkning:Kött från Sverige",
                       "märkning:Svenskt Kött", "namn:svensk"]   # see §14 V12, V20
    uteslut: [fryst, marinerad, grillkryddad, "lagat & klart"]
  Grönsaker:
    uteslut: [fryst]
  Skafferi: { frysbar: ja }
  Kryddor & Såser: { frysbar: ja }
  Fryst: { frysbar: ja }
omräkning:
  styckvikt_g: { gul lök: 150, rödlök: 120, vitlöksklyfta: 5, citron: 120 }
  densitet_g_per_dl: { vetemjöl: 60, strösocker: 85, jasminris: 85 }
```

`frysbar: ja` means "keeps; no overshoot cap". `storpack: ja` (and `storpack_varor`) means
"worth stocking up": bigger packs by jämförpris within the spend cap (§7). Frozen meat is excluded by default (buy
fresh, freeze at home); the user can remove `fryst` from `uteslut` to allow it.

## 8. Safety

Enforced in code, not in prompts.

1. **Endpoint allowlist** in `session.py`. The only permitted requests:
   `GET /search/mixed/`, `GET /products/<id>/`, `GET https://www.mathem.se/se/user/login/`,
   `POST /user/login/`, `GET /cart/`, `POST /cart/items/`. Anything else — including any
   URL containing `checkout`, `slot` or `order` — raises `ForbiddenEndpoint` before a
   request is made.
2. **Empty cart required.** `apply` reads the cart first and aborts if it has any line.
3. **Sanity limits** from `säkerhet`: abort if the plan total exceeds `max_total_kr` or any
   line exceeds `max_antal_per_rad`.
4. **Plan freshness:** abort if `06-mathem-plan.json` is older than `plan_max_ålder_h`.
   `apply` makes no decisions; it executes the plan verbatim.
5. **Credentials:** read from environment (`.env` loaded via `python-dotenv`). Never
   printed, logged, cached or written to the plan. The session cookie lives in memory only.
6. **Polite client:** User-Agent `meal-prep-bot/0.1 (+<MATHEM_BOT_CONTACT>)` where the
   contact comes from an env var (not hard-coded); ≤ 1 request/second; exponential backoff
   on 429/5xx honouring `Retry-After`; search responses cached per week in
   `.mathem-cache/` for 24 h.
7. `plan` never logs in.

## 9. CLI

Run with `uv run --project tools/mathem_cart mathem-cart <command>`.

| Command | Does |
|---|---|
| `plan [YYYY-MM-DD] [--no-input]` | Steps 1–6. Writes `06-mathem-plan.json` and `06-mathem-varukorg.md`. No login. Defaults to the latest week folder. |
| `apply [YYYY-MM-DD]` | Login, safety checks (§8), add every planned line, read the cart back, compare, update the report. |
| `pin <ingrediens> <produkt-id> [--fast]` | Add to `godkända` (or set `fast`) in `mathem-pins.yaml`. |
| `sök <term>` | Print the top 10 search results (id, name, package, price, jämförpris, deals). Used by the skill for the `s` option. |
| `eval` | For every pinned ingredient: search, run Laya, report precision/recall at the configured threshold against the pins. |

Exit codes: `0` ok, `2` plan has undecided items, `3` safety abort, `1` other errors.

### `06-mathem-plan.json`

```json
{
  "vecka": "2026-09-21",
  "skapad": "2026-09-24T18:02:11+02:00",
  "läge": "lär",
  "rader": [
    {"vara": "vispgrädde", "behov": {"mängd": 300, "enhet": "ml"},
     "kategori": "Mejeri & Ägg", "produkt_id": 6851,
     "namn": "Garant Vispgrädde 36%", "förpackning": "5 dl", "antal": 1,
     "kostnad_kr": 27.20, "jämförpris": "54.40 kr/l", "kampanj": null,
     "överköp": 0.67, "beslut": "pin", "flaggor": ["överköp"]}
  ],
  "undecided": [
    {"vara": "kycklingfilé", "behov": {"mängd": 1200, "enhet": "g"},
     "orsak": "lär-läge", "kandidater": [
       {"produkt_id": 1, "namn": "…", "förpackning": "…", "pris": 0, "jämförpris": "…",
        "kampanj": null, "p": 0.71}
     ]}
  ],
  "ej_med": ["Salt", "Svartpeppar"],
  "total_kr": 27.20
}
```

## 10. Pipeline integration

- **Skill** `.claude/skills/mathem-cart/SKILL.md` (`/mathem-cart [YYYY-MM-DD]`), runs in
  the main conversation:
  1. Find the week folder (argument or latest); require `03-handlingslista.md`.
  2. Check that `MATHEM_EMAIL`/`MATHEM_PASSWORD` are set (presence only, never print them).
  3. `plan --no-input`.
  4. For each `undecided` item: `AskUserQuestion` with the top 3 candidates plus
     "Hoppa över"; "Other" = a new search term → `sök`, then ask again. Save answers with
     `pin`. Re-run `plan --no-input` until nothing is undecided or everything left was
     skipped.
  5. Show the plan summary (total, number of lines, flags) and ask
     **"Vill du att jag lägger allt i varukorgen på Mathem nu?"** — `apply` only on yes.
  6. Run `apply`, show the verification result, and remind the user that checking and
     ordering happen in the Mathem app.
- **`meal-planning-hello-fresh` skill and `meal-planning-orchestrator`**: after the Notion
  question, one more optional question:
  **"Vill du att jag fyller varukorgen på Mathem (experimentellt)?"** → `/mathem-cart`.
- **CLAUDE.md**: add the phase to the structure tree, the architecture diagram and a short
  "Mathem-varukorg (experimental, optional)" section pointing to this spec.
- **`.gitignore`**: add `!tools/mathem_cart/pyproject.toml` (the repo ignores `*.toml`).
  `.env*` is already ignored.

## 11. Error handling

| Situation | Behaviour |
|---|---|
| API response missing an expected field | `MathemProtocolError` naming the endpoint and field; exit 1 |
| 401/403 during apply | Re-login once, then abort with "logga in igen / kontrollera .env" |
| Failure midway through apply | Stop, read the cart back, write exactly what got in to the report, exit 1. The user empties the cart and re-runs. |
| Product unavailable at apply time | Add the rest; list it in the report as a difference |
| Laya missing / fails to load | Warn once, continue in `lär` mode ordered by jämförpris |
| `03` missing | Exit 1 with the path that was expected |

Future (not built): replace `apply` with an in-browser Laya/extension variant that uses
the user's existing browser session, so no password is stored.

## 12. Testing

`tools/mathem_cart/tests/`, pytest, no network and no Laya in unit tests.

- `test_shopping_list.py`: a fixture `03` covering decimal comma, fractions, ranges,
  checkboxes, `(verifiera)`, the skipped sections.
- `test_packaging.py`: `5 dl`, `1000 g`, `ca 430 g`, `Max 2 per kund, 700 g`, `3x400 g`,
  `6-pack`, the unit-price fallback and the disagreement flag.
- `test_quantity.py`: 1,2 kg chicken → 2 × 700 g (60,95 kr) at 121,90 kr over
  2 × 1000 g; `2 för 99 kr`; `max_antal`; overshoot cap for Grönsaker; `frysbar` without a cap;
  all-over-cap fallback.
- `test_rules.py`: `uteslut`, `kräv_någon_av`, `föredra_någon_av`, availability.
- `test_session.py`: every non-allowlisted URL (incl. `checkout/confirm`, `/slots/`) raises
  before any request; credentials never appear in logged output.
- `test_applier.py`: fake cart client — non-empty cart aborts, limits abort, stale plan
  aborts, partial failure reports what got in, verification diff.
- `test_planner.py`: recorded search responses (`fixtures/search-vispgradde.json`,
  `fixtures/search-kycklingfile.json`, captured once from the live API) + stub matcher.
- `test_matcher_live.py`, marked `laya` and skipped unless Laya is installed: loads the
  router and scores two Swedish examples.
- CI: `.github/workflows/mathem-cart.yml` runs `uv run pytest -m "not laya"` on changes
  under `tools/mathem_cart/**`.
- Manual: `plan` on a real week, then `apply` by the user, then the user checks the cart
  in the Mathem app.

## 13. Open items to verify during implementation

1. ~~Whether `gross_price` already includes `-P%` discounts.~~ **Answered 2026-09-24
   (live): yes.** All 18 `-10%` products in a 28-term live sweep satisfy
   `gross_price = discount.undiscounted_gross_price × 0.9` to within 1 öre (e.g. 59.58 =
   66.20 × 0.9). `-P%` is therefore shown in the report as "(ingår i priset)" and never
   re-applied. `discount.maximum_quantity`, when set, is honoured: units beyond it are priced
   at `undiscounted_gross_price`.
2. ~~The exact shape of `availability`.~~ **Answered 2026-09-24 (live, 789 unique
   products):** `{"is_available": bool, "code": str, "description": str,
   "description_short": str}`. Codes seen: `available` (755, true), `sold_out_supplier`
   (17, false), `sold_out` (11, false), `available_later` (6, **true**). The code decides on
   `is_available`; a missing or malformed `availability` counts as unavailable.
3. ~~The exact Laya API.~~ **Answered 2026-09-24 (laya 0.3.20, run locally):**
   `Router().predict_batch([{"state": s, "questions": q}, …])` returns one result per
   request in order; P(true) is `result["answers"]["acceptabel"]["noul"]`. Batch and single
   `predict` give identical values. Swedish product states route to `laya-multilingual`
   ("Latin script … not safe for the English checkpoint"). First observation for item 4:
   zero-shot scores follow labels rather than the product (Garant Vispgrädde scored 0.53
   with the label "Från Sverige" and 0.21 without it, the same as an oat drink), and in a
   live dry run irrelevant products (a lemon cleaner for "citron", a beer for "koriander")
   scored ≈ 1.0. `lär` mode stays the default.
4. Laya's actual quality on Swedish product names (first `eval` after 2–3 weeks of pins).
5. The login response when credentials are wrong (for a clear error message).

## 14. Implementation notes (2026-09-24)

Deviations from this spec, decided during planning and implementation. 

| # | Deviation |
|---|---|
| V1 | Package layout: code in `tools/mathem_cart/mathem_cart/`, client and licence in `tools/mathem_cart/mathem_cart/mathem/`. |
| V2 | Live paging key is `attributes.has_more_items`; models accept snake_case and camelCase. |
| V3 | The `checkout`/`slot`/`order` ban applies to the URL **path**; query keys are allowlisted (`q type page group-by`), query values are free (`Slotts senap` must be searchable). |
| V4 | Cart and login requests send ha-mathem's `x-requested-case: camel` / `x-client-app` headers; search does not. |
| V5 | `förp knippe burk paket` mean a number of packages. |
| V6 | `plan_model.py` holds the plan/result dataclasses so `report.py` depends on nothing else. |
| V7 | `plan --hoppa <vara>` (repeatable) and `pin <vara> --sök <term>`; plan JSON gains `hoppade` and `varningar`. |
| V8–V10 | §13 items 1–3, answered above. |
| V11 | `plan`, `sök`, `eval` and `apply` exit 1 when `MATHEM_BOT_CONTACT` is unset. |
| V12 | Kött & Fisk also accepts the labels `Svensk Fågel`, `Kött från Sverige`, `Svenskt Kött`: no chicken in the live data carries `Från Sverige`, so the original rule rejected every fresh Swedish chicken. |
| V13 | POST is retried on 429 only, never on 5xx (cart quantities are deltas; a retried 502 could double an add). A `Retry-After` longer than 60 s (seconds or HTTP-date) aborts instead of waiting. Every redirect hop is allowlist-checked and rate-limited. |
| V14 | Spoon measures of a product that can't be converted (e.g. tomatpuré sold by weight) count as 1 package in any category, not only Kryddor & Såser. |
| V15 | `st` → `st` only matches one-for-one when the product names the same thing; otherwise it converts via `styckvikt_g` (8 vitlöksklyftor no longer buy 8 heads). `styckvikt_g` lookup also tries Swedish singular forms (citroner → citron). |
| V16 | `Max N per kund` and `discount.maximum_quantity` are enforced across all lines that resolve to the same product, and later lines are priced as that product's next units. |
| V17 | `apply` recomputes the total from the lines (the stored `total_kr` is not trusted), rejects NaN/negative costs, treats an unrecognised cart shape as non-empty (fail closed), and stops on 429 instead of skipping the remaining lines. |
| V18 | Package size is read from the last comma segment of `name_extra` when it starts with an origin or portion count (`Sverige, 3000 g`, `2 portioner, 500 g`) — about one live product in eight. |
| V19 | Command-line usage errors exit 1, so exit 2 keeps meaning "plan has undecided items". |
| V20 | Swedish origin is a preference, not a requirement (user decision 2026-09-24: imported is fine when nothing Swedish is available). New key `föredra_någon_av`; Kött & Fisk uses it instead of `kräv_någon_av`. Lines decided by Laya from a non-preferred product are flagged `ej föredragen`; pinned products are the user's choice and are not flagged. Before this, every salmon (Norwegian) was rejected. |
