---
name: mathem-cart
description: Tillval, experimentellt (av som standard, aktiveras med /setup mathem). Fyller varukorgen på Mathem från veckans 03-handlingslista.md via mathem-cart (plan → matchning med agenter → decide → frågor → apply). Lägger aldrig en beställning. Använd som valfritt steg efter Fas 5 eller fristående på en veckomapp.
argument-hint: "[YYYY-MM-DD]"
---

# Fyll Mathem-varukorgen (experimentell)

Gör om veckans `03-handlingslista.md` till en granskad plan och, efter användarens
uttryckliga ja, en fylld varukorg på Mathem. Python-CLI:t `mathem-cart` i
`tools/mathem_cart/` söker, filtrerar, räknar mängder och validerar. Agenterna
`mathem-matcher` (haiku, en per batch) och `mathem-granskare` (sonnet) bedömer vilka
produkter som är rätt vara. Skillen kör kommandona, skickar ut agenterna, ställer frågorna
och visar resultatet. Den fattar inga egna köpbeslut.

> **Grundregel: ingen beställning, inget ja-i-förväg, ingen `.env`.**
>
> - Lägg **aldrig** en beställning. Rör aldrig leveranstider, kassan eller betalning.
>   Verktyget kan inte heller göra det: alla sådana anrop stoppas i koden innan de skickas.
> - `apply` körs **bara** efter ett uttryckligt ja på exakt frågan i steg 6. Ett ja till
>   något annat (Notion-exporten, pipelinefrågan, en tidigare vecka) räknas inte.
> - Läs, visa eller skriv **aldrig** innehållet i `.env`. Kontrollera bara att variablerna
>   finns (steg 2). Skriv aldrig inloggningsuppgifter på kommandoraden
>   (`MATHEM_PASSWORD=… mathem-cart apply`). CLI:t läser dem själv från `.env`.
> - Agenterna skriver bara sina svarsfiler. De kör aldrig mathem-cart, aldrig apply och
>   läser aldrig .env.

**Detta körs i huvudkonversationen.** Skillen behöver `AskUserQuestion` och användarens eget
ja före `apply`. Delegera INTE till en subagent, och kör aldrig `apply` från en subagent.
Agenterna skickas ut härifrån; en subagent kan inte skicka ut agenter.

## Fasta värden

- **Kommando:** `uv run --project tools/mathem_cart mathem-cart <kommando>`, från repo-roten.
- **Filer i veckomappen:** `06-mathem-plan.json` (planen), `06-mathem-varukorg.md`
  (rapporten), `06-mathem-kandidater.json` (vad agenterna bedömer, aktuell omgång — för stor
  för en Read), `.mathem-matchning/` (en liten kandidatfil per del, svarsfiler och
  omgångarnas kopior), `.mathem-cache/` (sökcache, 24 h).
- **Regler och pins:** `tools/mathem_cart/mathem-regler.yaml`,
  `tools/mathem_cart/mathem-pins.local.yaml` (gitignorerad, skapas vid första pin).
- **Exitkoder:** `0` ok · `2` varor behöver beslut · `3` säkerhetsstopp · `4` matchning
  behövs · `1` övriga fel. Felmeddelanden går till stderr.

## Steg

0. **Är Mathem aktiverat?** Läs `integrations.mathem.enabled` i `meal-prep.local.yaml`
   (saknas filen gäller `meal-prep.example.yaml`, där Mathem är avstängt). Är det inte
   `true`, eller saknas `uv` (`command -v uv`), eller saknas `.env` (`test -f .env`):
   stoppa och säg åt användaren att köra `/setup mathem`. Mathem-integrationen är
   inofficiell och inte knuten till Mathem; den körs på användarens eget konto.

1. **Hitta veckomappen.**
   - Om `$ARGUMENTS[0]` angetts: använd `YYYY-MM-DD/`.
   - Annars: lista alla `YYYY-MM-DD/`-mappar (Glob) och välj den senaste. CLI:t väljer
     samma mapp när `vecka` utelämnas, men skriv ut den explicit i kommandona nedan.
   - Kräv att `03-handlingslista.md` finns. Saknas den: stoppa och föreslå att Fas 3 körs
     först.

2. **Kontrollera att variablerna finns, utan att visa värden.**

   ```bash
   for v in MATHEM_EMAIL MATHEM_PASSWORD MATHEM_BOT_CONTACT; do grep -q "^$v=." .env 2>/dev/null && echo "$v finns" || echo "$v saknas"; done
   ```

   - `MATHEM_BOT_CONTACT` (kontaktadress i User-Agent) krävs redan för `plan`, `decide`
     och `sök`. Saknas den: be användaren lägga in den i `.env` och stoppa.
   - `MATHEM_EMAIL` och `MATHEM_PASSWORD` behövs först för `apply`. Saknas de: fortsätt med
     planen, men säg att de måste finnas i `.env` före steg 7.
   - Variabler som är satta i skalets miljö räknas också (`.env` skriver aldrig över dem).
     Om kommandot säger "saknas" men användaren säger att de finns i miljön: lita på CLI:t,
     som namnger variabeln om den verkligen saknas.

3. **Gör planen.**

   ```bash
   uv run --project tools/mathem_cart mathem-cart plan <vecka> --no-input [--hoppa "<vara>" …]
   ```

   - `plan` söker, filtrerar med kategorireglerna och använder pins. Den loggar aldrig in,
     rör aldrig varukorgen och frågar aldrig. En ny `plan` kastar all tidigare matchning
     (`06-mathem-kandidater.json` och `.mathem-matchning/`).
   - `--hoppa` upprepas en gång per vara som användaren valt att hoppa över (steg 5). Håll
     listan över hela körningen och skicka med **alla** hoppade varor varje gång, både till
     `plan` och till `decide`.
   - **Exit 4** (stdout `N varor behöver matchning · omgång 1 · B batcher → …` följt av en
     rad per del) → steg 4.
   - **Exit 0** → steg 6. **Exit 2** → steg 5. **Exit 1 eller 3** → visa felmeddelandet
     och stoppa (se Felsökning).

4. **Matchningsloopen — högst två omgångar; `decide` nekar en tredje.**

   a. **Läs inte `06-mathem-kandidater.json`** — den är för stor för en Read, och
      produkterna är inte ditt jobb. `plan` och `decide` skriver i stället en rad per del på
      stdout, direkt efter sammanfattningsraden:

      ```
        batch 1: <vecka>/.mathem-matchning/omgang-1/batch-01-kandidater.json → <vecka>/.mathem-matchning/omgang-1/batch-01.json
        granskning: <vecka>/.mathem-matchning/omgang-2/granskning-kandidater.json → <vecka>/.mathem-matchning/omgang-2/granskning.json
      ```

      Notera varje rad: delen (`batch N` eller `granskning`), dess kandidatfil (före pilen)
      och dess svarsfil (efter pilen). Ändra aldrig filerna.

   b. Skicka ut **alla agenter i samma meddelande, i bakgrunden**: en `mathem-matcher` per
      `batch`-rad och, om det finns en `granskning`-rad, en `mathem-granskare`. Prompten är
      exakt tre rader med sökvägarna från delens rad, absoluta:

      ```
      Kandidatfil: <delens kandidatfil>
      Batch: <N>
      Svarsfil: <delens svarsfil>
      ```

      (granskaren: `Batch: granskning`). Inget annat: inga priser, inga egna produkttips.

   c. När alla har svarat:

      ```bash
      uv run --project tools/mathem_cart mathem-cart decide <vecka> --no-input [--hoppa "<vara>" …]
      ```

      - stderr `Skicka om: batch 3 → .mathem-matchning/omgang-1/batch-03.json (saknas)` eller
        `(ogiltigt: <fel>)`, stdout `Omgång N: K svar behöver skickas om → …`, exit 4:
        skicka ut **bara** de delarna igen (`Skicka om: granskning → …` gäller granskaren),
        med samma tre rader som förra gången för den delen plus `Förra svaret var ogiltigt: <fel>. Skriv svarsfilen på
        nytt.` när felet är `ogiltigt`. Kör sedan `decide` igen. `decide` tillåter en
        omsändning per del; nästa gång blir varorna oavgjorda.
      - stdout `Omgång 2 behövs: B batcher, granskning G varor → …` följt av en rad per
        del, exit 4: gör 4a–4c en gång till för omgång 2, med de nya raderna.
      - **Exit 0** → steg 6. **Exit 2** → steg 5. **Exit 1** → Felsökning.

   d. **Om agenttyperna saknas** (Agent-verktyget känner inte `mathem-matcher` eller
      `mathem-granskare` — t.ex. när agentfilerna skapades i samma session): stoppa.
      Skicka inte ut någon annan agenttyp i stället. En allmän agent har fler verktyg än
      Read och Write, och kan då köra CLI:t, ändra pins eller skriva i sökcachen — det är
      bara agenttypernas verktygslista som hindrar det. Säg till användaren att agenterna
      läses in när en session startar, och be hen starta en ny session och köra
      `/mathem-cart <vecka>` igen; den börjar om från steg 3 (sökningarna är cachade).

   Utan svarsfiler (till exempel när CLI:t körs utan Claude Code) blir omatchade varor
   oavgjorda med orsaken `matchning saknas`.

5. **Fråga om varje oavgjord vara.**

   Läs `undecided` i `<vecka>/06-mathem-plan.json` (Read). Varje post har `vara`, `behov`
   (`mängd`, `enhet`), `orsak`, `motivering` (modellens skäl, kan vara `null`) och upp till
   fem `kandidater` i Mathems sökordning med `produkt_id`, `namn`, `förpackning`, `pris`,
   `jämförpris` och `kampanj`.

   Per vara, ett `AskUserQuestion` (upp till fyra varor per anrop går bra):
   - **Fråga:** `<vara> — <mängd> <enhet> (<orsak>)`, plus ` — <motivering>` när den finns.
   - **Alternativ:** de tre första kandidaterna, var och en som
     `namn · förpackning · pris kr · jämförpris · kampanj` (skriv `—` för det som saknas),
     med `id <produkt_id>` i beskrivningen, plus alternativet **"Hoppa över"**.
   - **"Other"** betyder en ny sökterm.

   Vad orsaken betyder:
   - `matchning saknas`, `ogiltigt svar`, `besvarades inte`, `dubbelt svar`,
     `ogiltig sökterm` — agenten gav inget användbart svar. Fråga som vanligt.
   - `osäker`, `ingen passar` — modellen var osäker eller hittade inget som duger. Visa dess
     `motivering` i frågan.
   - `inga kandidater`, `mängd saknas`, `okänd enhet` — specialfall, se nedan.

   Hantera svaret:
   - **En kandidat** →
     `uv run --project tools/mathem_cart mathem-cart pin "<vara>" <produkt_id>`.
     Säger användaren att varan alltid ska vara exakt den produkten: lägg till `--fast`.
   - **Hoppa över** → lägg `--hoppa "<vara>"` till nästa `decide`-körning (och alla
     följande `plan`/`decide`). Varan hamnar under "Hoppade över" i rapporten och köps inte.
   - **Other (ny sökterm)** →
     `uv run --project tools/mathem_cart mathem-cart sök "<term>"`. Utdata är en rubrikrad
     följt av en rad per träff: `id  namn  förpackning  pris  jämförpris  kampanj`.
     Ställ frågan igen med de tre första träffarna plus "Hoppa över". Spara både valet och
     söktermen i ett anrop:
     `uv run --project tools/mathem_cart mathem-cart pin "<vara>" <produkt_id> --sök "<term>"`.
     Säger `sök` "Inga träffar": be om en annan term eller erbjud "Hoppa över".
   - Använd `vara` exakt som den står i planen. `pin` normaliserar namnet själv.

   Specialfall:
   - **`orsak` är `mängd saknas` eller `okänd enhet`**: kandidaterna visas, men en pin
     hjälper inte, eftersom mängden inte går att räkna. Erbjud "Hoppa över" (användaren
     lägger till varan själv i appen). Ändra inte `03-handlingslista.md` utan att fråga.
   - **`inga kandidater`**: be om en sökterm direkt (via `sök`) eller "Hoppa över".
   - **Samma vara kommer tillbaka** efter en pin (t.ex. ingen förpackning går att räkna för
     den valda produkten): fråga en gång till med nya kandidater, därefter föreslå
     "Hoppa över". Loopa inte.

   Kör sedan **`decide`** igen (inte `plan`), med samma `--no-input` och alla `--hoppa`:
   den återanvänder agenternas sparade svar utan nya agenter, och pins vinner över
   modellens val. Upprepa tills `decide` ger exit 0, det vill säga tills allt är avgjort
   eller hoppat över.

6. **Visa sammanfattningen och fråga.** Läs `06-mathem-varukorg.md` (och vid behov planen)
   och visa:
   - total (`total_kr`) och antal rader,
   - raden `Beslut: pin … · fast … · haiku … · sonnet …` från senaste `plan`/`decide`,
   - rader med flaggor: `överköp` (med procent), `ungefärlig`, `verifiera`,
     `storlek_osäker`, `ej föredragen` (inget svenskt fanns, så en importerad vara valdes),
     `storpack` (en större förpackning med lägre jämförpris valdes; den kostar lite mer nu),
     med modellens `motivering` för rader vars beslut är `haiku` eller `sonnet`,
   - hoppade varor (`hoppade`), varor som inte är med (`ej_med`, t.ex. salt och
     skafferivaror, och vin/öl markerade `köps på Systembolaget`) och eventuella varningar
     (`varningar`),
   - en länk till `<vecka>/06-mathem-varukorg.md`.

   Har en rad flaggan `för_många` kommer `apply` att stoppa på gränsen
   `max_antal_per_rad`. Lös det först (välj en större förpackning med `pin`, eller hoppa
   över) och kör `decide` igen.

   Fråga sedan exakt: **"Vill du att jag lägger allt i varukorgen på Mathem nu?"**

   Bara ett tydligt ja kör vidare. Allt annat (nej, tvekan, en följdfråga, en ändring) →
   kör inte `apply`. Ändras planen efter frågan: kör `decide` igen (steg 5), visa
   sammanfattningen och ställ frågan på nytt.

7. **Lägg i varukorgen.**

   ```bash
   uv run --project tools/mathem_cart mathem-cart apply <vecka>
   ```

   - `apply` läser planen, kontrollerar säkerhetsgränserna, loggar in, kräver en **tom**
     varukorg, lägger in planens rader precis som de står och läser tillbaka varukorgen.
   - `Inget att lägga i varukorgen.` (exit 0) → planen har inga rader. Säg det och stoppa.
   - **Exit 3** → säkerhetsstopp, ingenting är tillagt. Förklara orsaken från meddelandet:
     - varukorgen är inte tom → användaren tömmer den på mathem.se och säger till, sedan
       körs `apply` igen (ingen ny fråga behövs om planen är oförändrad),
     - planen är äldre än `säkerhet.plan_max_ålder_h` i `tools/mathem_cart/mathem-regler.yaml` (meddelandet visar gränsen) → kör steg 3–6 igen,
     - en rad över `max_antal_per_rad` → visa gränsen och raden; ändra planen (steg 5)
       eller låt användaren justera `mathem-regler.yaml`.
   - **Exit 1** →
     - saknad `MATHEM_EMAIL`/`MATHEM_PASSWORD`: meddelandet namnger variabeln (aldrig
       värdet). Be användaren lägga in den i `.env`.
     - `Inloggningen misslyckades`: ingenting är tillagt. Be användaren kontrollera
       e-post och lösenord i `.env`.
     - fel mitt i (stderr säger `Töm varukorgen på mathem.se och kör apply igen`): visa
       rapportens avsnitt `## Resultat i varukorgen` (det som faktiskt kom in) och be
       användaren **tömma varukorgen** innan `apply` körs igen.

8. **Visa verifieringen.** Visa stdout-raden (`N st av M produkter i varukorgen · K
   avvikelser`), varje `Avvikelse:`-rad från stderr och rapportens avsnitt
   `## Resultat i varukorgen`. Avsluta med:
   **Ingen beställning är gjord — kontrollera varukorgen och beställ själv i Mathem-appen.**

## Felsökning

Läs [felsokning.md](felsokning.md) när ett kommando ger en exitkod eller ett meddelande som stegen ovan inte täcker.

## Notis om workflow

Detta är det valfria, experimentella sista steget i matplaneringsworkflowet, efter
`export-to-notion`. Det kan också köras fristående på en befintlig veckomapp via
`/mathem-cart [YYYY-MM-DD]`. Design och säkerhetsregler:
[spec](../../../docs/design/mathem-varukorg.md); matchningen med
agenter: [matchningsspec](../../../docs/design/mathem-matchning.md).
Kommandon och miljövariabler: [tools/mathem_cart/README.md](../../../tools/mathem_cart/README.md).
