---
name: meal-planning-hello-fresh
description: Skapar HelloFresh-liknande matplanering för veckan. Använd när användaren nämner matplan, veckomeny, handlingslista, meal prep, matlådor eller HelloFresh. Orkestrerar specialiserade agenter genom 5 faser med obligatoriska stoppunkter, eller kör allt i huvudkonversationen i läge enkel för att spara tokens.
argument-hint: "[enkel | multi]"
---

# Matplanering (HelloFresh-stil) — Multi-Agent Workflow (eller enkelt läge)

## Quick start

När användaren vill planera mat för kommande vecka:

1. Läs hushållsprofilen: `meal-prep.local.yaml`, annars `meal-prep.example.yaml` (se
   [Hushållsprofil](reference.md#hushållsprofil)). Saknas den lokala filen, föreslå en
   gång att användaren kör `/setup` först — men fortsätt med mallens värden om hen
   hellre vill börja direkt.
2. Skapa datum-mapp i projektroten: `YYYY-MM-DD/` (måndagen för veckan).
3. Bestäm arbetsläge (se [Arbetsläge](#arbetsläge-multi-eller-enkel)) och säg vilket
   som gäller i en mening.
4. Följ faserna nedan — i läge `multi` delegerar du till specialiserade agenter, i läge
   `enkel` gör du samma arbete själv.
5. **Gå aldrig vidare utan användarens uttryckliga godkännande.** Stoppunkterna är
   desamma i båda lägena.

## Arbetsläge: multi eller enkel

Läget avgör vem som gör arbetet, inte vad som levereras: samma filer (`01`–`05`), samma
receptstandard, samma stoppunkter och samma hårda krav (allergier).

Välj läge i den här ordningen:
1. `$ARGUMENTS` är `enkel` eller `multi`.
2. Användaren säger det i konversationen ("spara tokens", "kör utan agenter", "kör
   enkelt" → `enkel`; "kör med agenter" → `multi`). Gäller veckan, inte profilen.
3. `workflow.mode` i hushållsprofilen. Saknas nyckeln: `multi`.

Byter användaren läge mitt i veckan gäller det nya läget från nästa fas. Filerna på
disk är överlämningen, så inget behöver göras om.

### Läge `multi` (standard)

Faserna nedan som de står: en specialistagent per fas och en `recipe-researcher` per
rätt, parallellt. Bredast receptsökning, men varje subagent startar med egen kontext
(systemprompt, `CLAUDE.md`, regler) och läser om det huvudkonversationen redan vet, så
tokenförbrukningen blir betydligt högre.

### Läge `enkel` (spara tokens)

Spawna **inga** subagenter. Gör varje fas själv i huvudkonversationen och följ
agentfilen som arbetsbeskrivning — den är källan till hur fasen görs, i båda lägena:

| Fas | Arbetsbeskrivning | Skillnad mot `multi` |
|---|---|---|
| 1 | `.claude/agents/brainstorming-agent.md` | 8–12 kandidater i stället för 10–20 |
| 2 | `.claude/agents/recipe-researcher.md` | En rätt i taget, se nedan |
| 2 (eget recept) | `.claude/agents/recipe-creator.md` + `.claude/agents/kockgranskare.md` | Kockgranskningen är en egenkontroll, se nedan |
| 3 | `.claude/agents/shopping-list-generator.md` | — |
| 4 | `.claude/agents/recipe-compiler.md` | Kör korskontrollen själv, se nedan |
| 5 | `.claude/agents/meal-prep-optimizer.md` | — |

Läs bara den fil som behövs för fasen du är i, när du kommer dit — inte alla i förväg.
Agentfilernas "du får det från orkestratorn" betyder här profilen och konversationen.

Sparsamt i Fas 2:
- Börja i receptbiblioteket: finns rätten i `recipe/` (Glob på slug), använd det och sök
  inte på webben.
- Annars 2–3 källor per rätt i stället för 3–5. Sök först på de högst prioriterade
  källorna i [reference.md](reference.md#svenska-receptkällor-prioritet); hämta bara
  sidor du faktiskt överväger. Läs inte om en sida du redan hämtat.
- Skriv `02-receptval.md` efter varje rätt, så att resultatet ligger på disk och inte
  bara i kontexten.

Kvalitetsgrindarna i läge `enkel`:
- `PostToolUse`-hooken validerar varje receptfil du skriver, precis som för agenterna.
  `SubagentStop`-grinden gäller däremot bara subagenter, så **du** är grinden: gå inte
  vidare från en fas medan en receptfil har `FEL`.
- Eget recept: efter `recipe-creator.md`-stegen, läs `kockgranskare.md` och gå igenom
  receptet mot dess checklista en gång (kritisk väg, dödtid, sådant som kallnar, byten,
  tidsraden räknad ur stegen). För in fynden direkt och säg kort vad du ändrade. Ryms
  tidsraden inte i nivån: fråga användaren, som i `multi`.
- Efter Fas 4: kör `python3 .claude/hooks/validate_week.py <YYYY-MM-DD>/` och rätta
  `FEL` innan Fas 5.

Tillvalen efter Fas 5 körs som vanligt. Mathem-varukorgens matchare (`mathem-matcher`,
haiku) är redan det billigaste steget och körs som subagenter även i läge `enkel`, så
att produktbedömningen inte hamnar på huvudkonversationens dyrare modell.

**Om kostnaden.** `enkel` sparar den kontext varje subagent annars bygger upp från
början, och den parallella breda sökningen. Allt arbete hamnar i stället på
huvudkonversationens modell, så besparingen är störst med en mindre modell
(`/model sonnet`). Kontexten växer under veckan: föreslå `/compact` mellan Fas 2 och
Fas 3 om den blir lång — filerna på disk bär allt som behövs.

## Antaganden (default)

- **Språk**: svenska, metriska enheter (fast — inte konfigurerbart)
- **Måltider, portioner, protein, allergier, utrustning**: från hushållsprofilen
  (`household`, `diet`, `kitchen`). Användarens besked i konversationen går före.
- **Receptkällor**: prioritera kvalitet — Köket, Tasteline, Arla, Landleys Kök, internationella vid autenticitet
- **Arbetsläge**: `workflow.mode` i profilen, standard `multi` (se
  [Arbetsläge](#arbetsläge-multi-eller-enkel))
- **Nivåer**: Vardag / Standard / Avancerad, med nivåmixen frågad varje vecka (förslag
  `level_mix`, standard 3/1/1). Definitionerna och Vardags lyft-golv står i
  [reference.md](reference.md#nivåer).

## Agentarkitektur (läge `multi`)

```
Användare
    ↓
[Orchestrator / Huvudkonversation]
    ├── Fas 1: brainstorming-agent
    ├── Fas 2: recipe-researcher × N (PARALLELLT, en per rätt)
    │         + recipe-creator (vid behov)
    ├── Fas 3: shopping-list-generator
    ├── Fas 4: recipe-compiler
    └── Fas 5: meal-prep-optimizer
```

Faserna nedan beskriver läge `multi`. I läge `enkel` gäller tabellen ovan: samma
uppdrag och samma stoppunkter, men utan delegering.

## Fas 1 — Brainstorming

**Delegera till `brainstorming-agent`.**

Fråga först efter veckans nivåmix (hur många Vardag / Standard / Avancerad). Om
användaren inte svarar: använd förslaget 3/1/1 och säg det.

Ge agenten:
- Användarens preferenser (protein, tid, utrustning, smaker) — från hushållsprofilen
  plus det användaren säger nu. Allergier skickas som hårda krav.
- Antal måltider/dagar och portioner per recept
- Nivåmixen
- Datum-mapp

Agenten skriver `01-brainstorming.md` med 10-20 kandidater, var och en taggad med nivå.

### STOPP
Presentera listan. Be användaren välja rätter och/eller klistra in egna recept.

## Fas 2 — Receptval (PARALLELL FORSKNING)

**Spawna EN `recipe-researcher` per vald rätt — alla i bakgrunden, parallellt.**

Varje researcher:
- Söker 3-5 källor för sin specifika rätt
- Jämför kvalitet (inte bara första träff)
- Bedömer mot rättens nivå (tid, råvaror, lyft för Vardag)
- Returnerar: bästa länk, alternativ, originalportioner, kvalitetsbedömning

Ge varje researcher (och `recipe-creator`) rättens nivå från `01-brainstorming.md`.
Rätter som användaren lägger till själv (inklistrade recept, länkar, rätter som inte
står i `01`) saknar nivå — ge dem en enligt [Nivåer](reference.md#nivåer) och säg
vilken, så användaren kan ändra den.

**Exempel:**
```
5 valda rätter → 5 parallella recipe-researcher-agenter:
  Agent 1: "Hitta bästa recept för kycklingfajitas, 4 portioner, nivå Vardag, utan nötter"
  Agent 2: "Hitta bästa recept för laxpasta, 4 portioner, nivå Standard, utan nötter"
  Agent 3: "Hitta bästa recept för chili con carne, 4 portioner, nivå Vardag, utan nötter"
  ...
```

Efter alla researchers returnerat:
1. Syntetisera resultat till `02-receptval.md`
2. Beräkna skalningsfaktorer
3. Om eget recept behövs: spawna `recipe-creator` med rättens nivå, och kör sedan
   kockgranskningen enligt steg 3 i `.claude/skills/create-recipe/SKILL.md`
   (`kockgranskare` per nytt recept, parallellt)

### STOPP (obligatorisk)
Fråga: **"Vill du att jag skapar handlingslista nu?"**

## Fas 3 — Handlingslista

**Delegera till `shopping-list-generator`.**

Ge agenten:
- Alla recept med portioner och skalningsfaktorer
- Referens till `02-receptval.md` och `recept-*.md`-filer
- `diet.lactose_free` från hushållsprofilen

Agenten skriver `03-handlingslista.md`.

### STOPP (obligatorisk)
Fråga: **"Vill du att jag skapar receptsamling och meal prep-plan nu?"**

## Fas 4 — Receptsamling (standardiserade recept)

**Delegera till `recipe-compiler`.**

Ge agenten alla recept med skalningsfaktorer. Agenten hämtar recept från webblänkar och lokala filer, skalar ingredienser och standardiserar formatet. Skriver `04-alla-recept.md`.

Ingen separat stoppunkt — fortsätt direkt till Fas 5.

## Fas 5 — Meal prep-plan

**Delegera till `meal-prep-optimizer`.**

Ge agenten alla recept (baserat på `04-alla-recept.md`). Agenten skapar tidsoptimerad tillagningsplan i `05-meal-prep-plan.md`.

### Tillval efter Fas 5

Tillvalen är avstängda som standard. Erbjud bara de som är aktiverade i
hushållsprofilen (`integrations.<namn>.enabled: true`), i den här ordningen. Är inget
aktiverat: avsluta utan att fråga.

- **Notion** (`integrations.notion`): fråga **"Vill du exportera veckan till Notion?"**
  Om ja: kör skillen `export-to-notion` i huvudkonversationen, inte via subagent. Den
  skapar en översiktssida i veckodatabasen med undersidor för handlingslista och meal
  prep-plan, plus genvägar till recepten i receptdatabasen (recept dupliceras aldrig).
  Se [export-to-notion](../export-to-notion/SKILL.md).
- **Mathem** (`integrations.mathem`): fråga **"Vill du att jag fyller varukorgen på
  Mathem (experimentellt)?"** Om ja: kör skillen `mathem-cart` i huvudkonversationen.
  Den planerar varukorgen från `03-handlingslista.md`, frågar om osäkra varor och lägger
  in allt först efter ett uttryckligt ja. Den lägger aldrig en beställning. Se
  [mathem-cart](../mathem-cart/SKILL.md).

Klart! Ingen ytterligare stoppunkt efter detta.

## Ytterligare skills

- `/setup` — Skapa eller ändra hushållsprofilen och slå på tillval
- `/create-recipe [rätt] [portioner]` — Skapa ett eget recept från grunden
- `/verify-recipes [YYYY-MM-DD]` — Kontrollera receptstandarden och handlingslistan
- `/export-to-notion [YYYY-MM-DD]` — Tillval: exportera en färdig vecka till Notion
- `/mathem-cart [YYYY-MM-DD]` — Tillval, experimentellt: fyll Mathem-varukorgen

## Referens

För källor och konverteringar, se [reference.md](reference.md).
För exempel på format, se [examples.md](examples.md).
