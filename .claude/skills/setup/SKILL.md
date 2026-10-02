---
name: setup
description: Kom igång — skapar eller ändrar hushållsprofilen (meal-prep.local.yaml) och slår på tillval som Notion-export och Mathem-varukorg. Använd första gången repot används, när användaren säger "setup", "kom igång", "konfigurera", "ändra portioner/allergier/utrustning", eller vill aktivera eller stänga av Notion eller Mathem.
argument-hint: "[notion | mathem | visa]"
---

# Setup — hushållsprofil och tillval

Skriver `meal-prep.local.yaml` i projektroten: användarens egen profil, gitignorerad.
Mallen och standardvärdena står i `meal-prep.example.yaml` — läs den först, den
dokumenterar varje nyckel. Den lokala filen behöver bara innehålla det som skiljer sig
från mallen, men skriv gärna ut hela profilen så att den är lätt att läsa och ändra.

**Körs i huvudkonversationen** — skillen behöver `AskUserQuestion`, och Notion-delen
behöver Notion-verktygen. Skriv allt till användaren på svenska.

## Argument

- inget → hela flödet (steg 1–5)
- `visa` → visa nuvarande profil (lokal fil, annars mallen) i en kort tabell och stanna
- `notion` → bara steg 1 och Notion-delen av steg 4
- `mathem` → bara steg 1 och Mathem-delen av steg 4

## Regler

- Läs, visa eller skriv **aldrig** innehållet i `.env`. Kontrollera bara att nycklar finns.
- Slå aldrig på ett tillval som användaren inte uttryckligen valt.
- Ändra bara de nycklar användaren svarat på. Behåll allt annat i den lokala filen,
  inklusive kommentarer.
- Committa aldrig `meal-prep.local.yaml` eller `.env`.

## Steg

### 1. Förutsättningar

Kör (läser inga hemligheter):

```bash
for c in git python3 uv; do command -v "$c" >/dev/null && echo "$c: finns" || echo "$c: saknas"; done
python3 -c 'import sys; print("python", sys.version.split()[0])' 2>/dev/null
git rev-parse --is-inside-work-tree 2>/dev/null || echo "inte ett git-repo"
test -f meal-prep.local.yaml && echo "profil: finns" || echo "profil: saknas"
```

- `python3` (3.8+) krävs: hookarna som håller receptstandarden använder den. Saknas den,
  säg det och ge installationstips (macOS: `brew install python`, Debian/Ubuntu:
  `sudo apt install python3`, Windows: kör i WSL).
- `git` krävs: klona repot i stället för att ladda ner en zip.
- `uv` behövs bara för Mathem.

### 2. Befintlig profil?

Finns `meal-prep.local.yaml`: visa nuvarande värden i en kort tabell och fråga med
`AskUserQuestion` (multiSelect) vilka delar som ska ändras: Hushåll, Kost, Kök,
Nivåmix, Tillval. Ställ bara frågorna för de valda delarna. Har den lokala filen en
äldre `config_version` än mallen: lägg till nya nycklar med mallens värden och höj
versionen.

Finns den inte: kör alla delar.

### 3. Hushållet (AskUserQuestion, max 4 frågor per anrop)

**Omgång A — hushåll**
- Portioner per recept: 2 / 4 (rekommenderas) / 6 / 8 → `household.portions_per_recipe`
- Måltider: bara middag (rekommenderas) / lunch + middag → `household.meals`
- Nivåmix per vecka: 3 Vardag + 1 Standard + 1 Avancerad (rekommenderas) / bara Vardag /
  egen → `level_mix` och `household.dishes_per_week` (summan)
- Erfarenhet: hemmakock / van (rekommenderas) / yrkeskock → `cook.experience`

**Omgång B — kost och kök**
- Proteinfokus: varierat (rekommenderas) / högt protein / vegetariskt / pescetariskt
  → `diet.protein_focus`
- Allergier och sådant som ska undvikas: fritext via "Other" (t.ex. "nötter, koriander").
  Fråga om varje sak är en **allergi** (hårt krav → `diet.allergies`) eller bara ogillas
  (`diet.avoid`) om det inte är uppenbart.
- Utrustning utöver ugn och spis (multiSelect): airfryer, slow cooker, wok, sous vide,
  grill → `kitchen.equipment`
- Laga det mesta i ett pass (meal prep) eller varje dag? → `kitchen.weekend_prep`

### 4. Tillval (AskUserQuestion, multiSelect, inget förvalt)

Fråga vilka tillval som ska vara på. Båda är av som standard; gå bara vidare med de
användaren väljer. Tillval som användaren väljer bort sätts till `enabled: false`.

**Notion — exportera veckan till Notion**
1. Kontrollera att `notion-*`-verktyg finns i sessionen. Finns de inte: förklara att
   Notion-kopplingen måste anslutas i Claude Code först (`/mcp`, eller Connectors på
   claude.ai), låt `enabled: false` stå och gå vidare.
2. Fråga om användaren redan har en databas för veckor och en för recept, eller vill
   att du skapar dem.
   - **Har redan:** sök med `notion-search` på namnen användaren anger, hämta varje
     databas med `notion-fetch` och läs av data source-URL:en (`collection://…`).
     Visa vad du hittade och be om bekräftelse.
   - **Skapa:** fråga under vilken sida de ska ligga, och skapa två databaser med
     `notion-create-database`: "Veckor" (titelfält `Name`) och "Recept" (titelfält
     `Name`). Läs av data source-URL:erna.
3. Skriv `integrations.notion.weeks_data_source`, `recipes_data_source` och
   `enabled: true`.

**Mathem — fyll varukorgen (experimentellt)**
1. Visa först, ordagrant: *"Mathem-integrationen är inofficiell och inte knuten till
   Mathem. Den använder ditt eget konto, kan sluta fungera när Mathem ändrar sin sajt,
   och lägger aldrig en beställning — du granskar och beställer själv i appen."* Fråga
   om användaren vill fortsätta.
2. Kräv `uv` och Python 3.11+. Kör `uv sync --project tools/mathem_cart`.
3. Finns ingen `.env`: kör `cp .env.example .env` och be användaren fylla i
   `MATHEM_EMAIL`, `MATHEM_PASSWORD` och `MATHEM_BOT_CONTACT` (sin egen e-post eller
   URL) själv i en editor. Skriv aldrig värdena åt hen.
4. Kontrollera nycklarna utan att visa värden:
   ```bash
   for v in MATHEM_EMAIL MATHEM_PASSWORD MATHEM_BOT_CONTACT; do grep -q "^$v=." .env 2>/dev/null && echo "$v finns" || echo "$v saknas"; done
   ```
5. När `MATHEM_BOT_CONTACT` finns: testa sökningen med
   `uv run --project tools/mathem_cart mathem-cart sök mjölk` (loggar inte in).
6. Skriv `integrations.mathem.enabled: true`.

### 5. Skriv profilen och sammanfatta

- Skriv `meal-prep.local.yaml` med Write: utgå från mallens struktur och kommentarer,
  med användarens värden. Läs tillbaka filen och kontrollera indrag och listor.
- Valfritt: fråga om WebSearch och WebFetch ska tillåtas utan fråga i
  `.claude/settings.local.json` (färre behörighetsfrågor i Fas 2). Lägg bara till dem
  vid ja, och bevara det som redan står i filen.
- Sammanfatta i en kort tabell: vad som sparats, vilka tillval som är på, och nästa
  steg: *"Skriv till exempel: Planera mat för veckan."*
