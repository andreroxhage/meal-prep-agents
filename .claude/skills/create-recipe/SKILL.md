---
name: create-recipe
description: Skapar ett eget högkvalitativt recept från grunden. Använd när användaren vill skriva ett eget recept, anpassa ett befintligt recept, eller skapa något unikt. Delegerar till recipe-creator-agenten.
argument-hint: "[rättens namn] [portioner]"
---

# Skapa eget recept

Användaren vill skapa ett eget recept. Delegera till `recipe-creator`-agenten.

## Steg

1. **Samla information** från användaren:
   - Vilken rätt? (`$ARGUMENTS[0]` om angivet)
   - Antal portioner? (`$ARGUMENTS[1]` om angivet, default: `household.portions_per_recipe` i `meal-prep.local.yaml`, annars
     `meal-prep.example.yaml`)
   - Nivå? (Vardag / Standard / Avancerad, se `## Nivåer` i
     `.claude/skills/meal-planning-hello-fresh/reference.md`). Säger användaren inget:
     föreslå en utifrån rätten och säg vilken.
   - Speciella önskemål (allergier, anpassningar)?
   - Inspiration (befintligt recept att utgå från)?

2. **Spawna `recipe-creator`-agenten** med uppdraget:
   - Rätt: [namn]
   - Portioner: [antal]
   - Nivå: [Vardag / Standard / Avancerad]
   - Anpassningar: [om relevant]
   - Datum-mapp: aktuell veckas `YYYY-MM-DD/`

3. **Leverera resultatet** till användaren:
   - Visa receptet
   - Fråga om justeringar behövs

## Format

Receptet följer `.claude/rules/recipe-style.md`. Viktigast: **mängden ska stå i
instruktionsstegen**, inte bara i ingredienslistan — och den mängd som står där ska
vara den läsaren faktiskt tar, även när steget körs i omgångar. Formatet kontrolleras
automatiskt när agenten skriver filen — `recipe-creator` får eventuella fel
tillbaka och rättar dem innan den är klar.

## Filnamnskonvention

Receptfilen sparas som: `YYYY-MM-DD/recept-<slug>-<portioner>p.md`

Exempel:
- `2026-03-02/recept-kycklingfajitas-6p.md`
- `2026-03-02/recept-pulled-beef-tortillas-8p.md`
