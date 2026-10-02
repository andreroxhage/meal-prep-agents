---
name: meal-planning-hello-fresh
description: Skapar HelloFresh-liknande matplanering för veckan. Använd när användaren nämner matplan, veckomeny, handlingslista, meal prep, matlådor eller HelloFresh. Orkestrerar specialiserade agenter genom 5 faser med obligatoriska stoppunkter.
---

# Matplanering (HelloFresh-stil) — Multi-Agent Workflow

## Quick start

När användaren vill planera mat för kommande vecka:

1. Läs hushållsprofilen: `meal-prep.local.yaml`, annars `meal-prep.example.yaml` (se
   [Hushållsprofil](reference.md#hushållsprofil)). Saknas den lokala filen, föreslå en
   gång att användaren kör `/setup` först — men fortsätt med mallens värden om hen
   hellre vill börja direkt.
2. Skapa datum-mapp i projektroten: `YYYY-MM-DD/` (måndagen för veckan).
3. Följ faserna nedan — delegera till specialiserade agenter.
4. **Gå aldrig vidare utan användarens uttryckliga godkännande.**

## Antaganden (default)

- **Språk**: svenska, metriska enheter (fast — inte konfigurerbart)
- **Måltider, portioner, protein, allergier, utrustning**: från hushållsprofilen
  (`household`, `diet`, `kitchen`). Användarens besked i konversationen går före.
- **Receptkällor**: prioritera kvalitet — Köket, Tasteline, Arla, Landleys Kök, internationella vid autenticitet
- **Nivåer**: Vardag / Standard / Avancerad, med nivåmixen frågad varje vecka (förslag
  `level_mix`, standard 3/1/1). Definitionerna och Vardags lyft-golv står i
  [reference.md](reference.md#nivåer).

## Agentarkitektur

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
3. Om eget recept behövs: spawna `recipe-creator` med rättens nivå

### STOPP (obligatorisk)
Fråga: **"Vill du att jag skapar handlingslista nu?"**

## Fas 3 — Handlingslista

**Delegera till `shopping-list-generator`.**

Ge agenten:
- Alla recept med portioner och skalningsfaktorer
- Referens till `02-receptval.md` och `recept-*.md`-filer

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
