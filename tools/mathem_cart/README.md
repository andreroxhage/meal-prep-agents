# mathem-cart (Fas 6, experimentell)

Gör om veckans `03-handlingslista.md` till en granskad plan och, bara när du själv kör
`apply`, en fylld varukorg på Mathem. **Verktyget lägger aldrig en beställning** — du
kontrollerar och beställer i Mathem-appen. Design: [spec](../../docs/design/mathem-varukorg.md);
matchningen: [matchningsspec](../../docs/design/mathem-matchning.md).

> **Inofficiellt.** Verktyget är inte knutet till eller godkänt av Mathem. Det använder
> ditt eget konto och Mathems webb-API så som webbläsaren gör, och kan sluta fungera när
> Mathem ändrar sin sajt. Använd på egen risk. Integrationen är avstängd tills du kör
> `/setup mathem` (`integrations.mathem.enabled` i `meal-prep.local.yaml`).

## Kommandon

Kör med `uv run --project tools/mathem_cart mathem-cart <kommando>`.

- `plan [ÅÅÅÅ-MM-DD] [--no-input] [--hoppa VARA]` — söker, filtrerar och använder pins; skriver
  `06-mathem-kandidater.json` och avslutar med exit 4 när varor behöver matchning; annars planen
  (`06-mathem-plan.json` + `06-mathem-varukorg.md`). Loggar aldrig in och frågar aldrig
  (`--no-input` godtas men ignoreras).
- `decide [ÅÅÅÅ-MM-DD] [--no-input] [--hoppa VARA]` — läser agenternas svar i `.mathem-matchning/`,
  validerar dem och skriver planen; exit 4 när en andra omgång eller en omsändning behövs; frågar
  i terminalen utan `--no-input`. Loggar aldrig in.
- `apply [ÅÅÅÅ-MM-DD]` — lägger planens rader i en tom varukorg och jämför efteråt.
- `pin <ingrediens> [produkt-id] [--fast] [--sök TERM]` — sparar val i `mathem-pins.local.yaml` (gitignorerad; formatet står i `mathem-pins.example.yaml`).
- `sök <term>` — visar de 10 första sökträffarna (id, namn, förpackning, pris, jämförpris, kampanj).

Gemensamma flaggor: `--root`, `--regler`, `--pins`. Exitkoder: 0 ok, 2 oavgjort, 3 säkerhetsstopp,
4 matchning behövs, 1 fel.

## Matchning

CLI:t anropar aldrig en modell och behöver ingen API-nyckel. `/mathem-cart` skickar ut
`mathem-matcher` (haiku), en per batch (batchstorlek `BATCH_SIZE` i `mathem_cart/candidates.py`), och `mathem-granskare` (sonnet) för
de varor matcharen var osäker på; högst två omgångar. Varje agent läser bara sin del,
`.mathem-matchning/omgang-N/batch-NN-kandidater.json` (granskaren `granskning-kandidater.json`);
`plan` och `decide` skriver en rad per del på stdout. Agenterna ser aldrig priser, och
modellens val sparas aldrig som pins. Utan Claude Code blir omatchade varor oavgjorda med
orsaken `matchning saknas`. Detaljer: [matchningsspec](../../docs/design/mathem-matchning.md).

## Regler som gör listan beställbar (`mathem-regler.yaml`)

- `köps_inte_på_mathem`: ord per ställe (i dag `Systembolaget`: vin, öl, lager …). En vara
  vars huvudord (sista ordet före ett eventuellt kommatecken) är ett av orden matchas aldrig
  och listas under "Ej med" som
  "köps på Systembolaget". Lägg till egna ställen för varor Mathem inte har.
- `storpack: ja` (per kategori: Kött & Fisk, Skafferi, Kryddor & Såser, Fryst) och
  `storpack_varor` (huvudord: smör, ost, ägg, vitlök, tortillas …): varor som håller sig. Där väljs
  lägst jämförpris för det som faktiskt köps (kampanjer inräknade) bland alternativen som
  kostar högst `storpack_max_merkostnad` (50 %) eller `storpack_max_merkostnad_kr` (100 kr),
  det som är minst, mer än det billigaste. Raden flaggas `storpack` när en större förpackning
  valdes. Övriga varor: lägst totalkostnad inom `max_överköp`. Agenterna får också upp till 5
  extra kandidater med lägst jämförpris, så storpack hittar storförpackningar längre ner i sökningen.
- `basvaror` (huvudord: potatis, lök, morötter, ris, pasta, couscous, linser, havregryn …):
  billiga baslivsmedel som köps i storpack. Storpackens 50 % räcker aldrig för en påse för
  20 kr, så här gäller bara `max_merkostnad_kr` (150 kr) mer än det billigaste, och den större
  förpackningen måste sänka jämförpriset med minst `min_besparing` (15 %) och får vara högst
  `max_gånger_behovet` (20) gånger behovet. Värdet per vara är största mängd att köpa totalt
  (`potatis: 5 kg`); tomt = inget tak, `nej` = stängd. Går före `storpack_varor` och
  kategorins `storpack`, utom när ett ord i namnet står i `utom` (färsk, picklad, inlagd …:
  "färsk pasta" köps som färskvara). Raden flaggas `storpack`. Nya varor läggs till i listan.
- `tillåt_fryst` (huvudord: kycklingfilé, torskfilé, laxfilé …): fryst produkt duger trots
  `uteslut: [fryst]` i Kött & Fisk. Står "färsk" i listan väljs ändå färskt. Bladörter till
  Vardag/Standard skriver Fas 3 som `<ört>, fryst` under Fryst (se `## Nivåer` i
  `reference.md`); till Avancerad köps de färska.
- `omräkning.styckvikt_g`: gram per styck för varor listan räknar i styck. En förpackning
  som säljs per vikt räknas som sin vikt i hela styck, minst ett ("Gurka, 270 g" är en gurka).

## Miljövariabler (`.env` i repo-roten, gitignorerad)

- `MATHEM_EMAIL`, `MATHEM_PASSWORD` — bara för `apply`. Skrivs aldrig ut, loggas eller sparas.
- `MATHEM_BOT_CONTACT` — **din egen** kontaktadress (e-post eller URL) i User-Agent; krävs av
  `plan`, `decide`, `sök` och `apply`. Mallen finns i `.env.example`.

## Säkerhet (spec §8)

- Endast sex tillåtna anrop (sök, produkt, inloggning, läs/lägg i varukorg); allt annat stoppas före anropet.
- `apply` kräver en tom varukorg och avbryter annars.
- Gräns från `mathem-regler.yaml`: `max_antal_per_rad` (inget tak för varukorgens total).
- Planen får vara högst `plan_max_ålder_h` gammal; `apply` fattar inga egna beslut.
- Inloggningsuppgifter läses bara från miljön; sessionen finns bara i minnet.
- Högst 1 anrop/s, backoff på 429/5xx, sökningar cachas per vecka i `.mathem-cache/` i 24 h.
- `plan` och `decide` loggar aldrig in.
