---
name: verify-recipes
description: Kontrollerar att recept följer receptstandarden (mängder i instruktionerna, format, enheter) och att handlingslistan täcker receptsamlingen. Använd före export, efter manuell redigering av recept, eller när användaren vill kvalitetssäkra en vecka.
argument-hint: "[YYYY-MM-DD eller filsökväg]"
---

# Verifiera recept

Kör den maskinella kontrollen av receptstandarden (`.claude/rules/recipe-style.md`)
och rapportera resultatet till användaren.

## Steg

1. **Bestäm omfattning** från `$ARGUMENTS`:
   - Veckomapp (`YYYY-MM-DD`) → alla `recept-*.md` och `04-alla-recept.md` i mappen,
     plus korskontroll mot `03-handlingslista.md`.
   - Filsökväg → bara den filen.
   - Inget argument → alla receptfiler i `recipe/` samt senaste veckomappen.

2. **Kör receptkontrollen** (utan `--fix` först, så att användaren ser vad som är fel):

   ```bash
   python3 .claude/hooks/validate_recipe.py <filer...>
   ```

3. **Kör korskontrollen** när det finns både `03-handlingslista.md` och
   `04-alla-recept.md`:

   ```bash
   python3 .claude/hooks/validate_week.py <YYYY-MM-DD>/
   ```

4. **Rätta felen**. `FEL` ska åtgärdas, inte förklaras bort:
   - Mekaniska avvikelser (decimalpunkt, saknat mellanslag, fel ordning på
     ingrediensraden): kör om med `--fix` så rättas de automatiskt.
   - `Regel 1` (mängd saknas i steget) och `Regel 2` (oanvänd ingrediens): skriv om
     steget. Detta är hela poängen med standarden — läsaren ska slippa scrolla.
   - `TIPS` är förslag: rätta dem om de är rimliga, annars låt dem stå.

5. **Kockgranskning (på begäran)**: den maskinella kontrollen ser inte om stegen står i
   rätt tidsordning eller om tidsraden stämmer (Regel 9). Ber användaren om det, eller
   ska ett recept in i `recipe/`, spawna en `kockgranskare` per recept, parallellt, och
   för in fynden. Den kostar en modellkörning per recept, så den körs inte annars.

6. **Rapportera** till användaren: hur många filer som kontrollerades, vad som
   rättades automatiskt, vad som rättades manuellt och vad som eventuellt kvarstår.

## Noteringar

- Kontrollen körs också automatiskt som `PostToolUse`-hook varje gång ett recept
  skrivs eller redigeras, och som `SubagentStop`-gate för `recipe-creator` och
  `recipe-compiler`. Den här skillen är för manuell körning över redan befintliga
  filer.
- Alla recept i `recipe/` följer standarden, och CI kontrollerar hela biblioteket vid
  varje körning. Ett `FEL` i `recipe/` är därför en regression som ska rättas.
