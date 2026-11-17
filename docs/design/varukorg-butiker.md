# Fas 6 — varukorgen hos fler butiker (Mathem + Willys)

**Status:** implementerad 2026-11-17 i `tools/mathem_cart/` (Willys `apply` ej provkörd mot ett
riktigt konto). Bygger på [mathem-varukorg.md](mathem-varukorg.md) och
[mathem-matchning.md](mathem-matchning.md); allt där gäller för alla butiker om inget annat
står här.

## Varför

En jämförelse av en riktig vecka (37 varor, 2026-11-23) gav Willys ca 1 029 kr för varorna
mot Mathems 1 306 kr, alltså ca 21 % billigare, före avgifter (Willys ca 158 kr i
leverans och plock enligt tredjepartssidor, ej verifierat). Ägaren vill kunna välja en
billigare butik utan att tappa det granskade flödet plan → matchning med agenter →
decide → frågor → apply.

## Beslut

| # | Fråga | Beslut |
|---|---|---|
| B1 | Generalisera eller kopiera `mathem-cart`? | **Generalisera.** Samma CLI, regler, planerare, agenter och skill. Butiken väljs med `--butik`. |
| B2 | cartway som MCP eller egen Python-klient? | **Egen Python-klient** (`mathem_cart/willys/`), med cartways kartlagda HTTP-anrop som källa (MIT). Se §3. |
| B3 | Hur väljs butik? | `--butik mathem\|willys` på CLI:t (standard `mathem`, så allt som fanns fungerar som förut). Skillen tar butiken från argumentet, annars den butik som är påslagen i profilen (`integrations.<butik>.enabled`), och frågar om båda är på. |
| B4 | Filer per butik | `06-<butik>-plan.json`, `06-<butik>-varukorg.md`, `06-<butik>-kandidater.json`, `.<butik>-matchning/`, `.<butik>-cache/`, `<butik>-regler.yaml`, `<butik>-pins.local.yaml`. Mathems namn är oförändrade. |
| B5 | Produkt-id | `int` för Mathem, sträng för Willys (`101106287_ST`). Planen, pins och agentsvar tar båda. |

## 1. Butiksgränssnittet

`mathem_cart/stores.py` har en `Store` per butik. Resten av koden känner bara till den:

| Del | Mathem | Willys |
|---|---|---|
| session (tillåtna anrop, User-Agent, 1 anrop/s, backoff) | `MathemSession` | `WillysSession` (ärver backoff och takt, egen lista över tillåtna anrop) |
| sök + produkt → `Product` | `ProductsClient` | `WillysProducts` |
| varukorg: läs, lägg till | `CartClient` | `WillysCart` |
| inloggning (bara `apply`) | `MATHEM_EMAIL`, `MATHEM_PASSWORD` | `WILLYS_USERNAME` (personnummer eller Willys Plus-nummer), `WILLYS_PASSWORD` |

Willys-svaret översätts till samma `Product` som Mathem, så filter, mängdräkning,
kampanjer, storpack, agenter och rapport är oförändrade. Kontaktadressen i User-Agent
läses från `BOT_CONTACT`, annars `MATHEM_BOT_CONTACT`.

## 2. Willys-sökningen (verifierad 2026-11-17, utan inloggning)

`GET https://www.willys.se/search?q=<term>&size=<n>&page=<n>` med `Accept: application/json`
ger `results[]` och `pagination` (`currentPage` från 0, `numberOfPages`). Fält som används:

| Fält | Exempel | Blir |
|---|---|---|
| `code` | `101106287_ST`, `100149359_KG` | `id`. Suffixet är säljenheten: `_KG` säljs per vikt. |
| `name`, `manufacturer` | `Nötfärs 12% Sverige`, `GARANT` | `full_name`, `brand` |
| `displayVolume` / `productLine2` | `500g`, `ca: 200g`, `GARANT, 500g` | förpackning; `ca:` → ungefärlig |
| `priceValue`, `priceUnit` | `59.9`, `kr/kg` | pris. För `_KG` är det kr/kg, så priset per styck = `priceValue × averageWeight`. |
| `comparePrice`, `comparePriceUnit` | `59,90 kr`, `kg` | jämförpris |
| `averageWeight` | `0.2` (kg) | storlek för `_KG`-varor |
| `potentialPromotions[]` | se nedan | kampanj |
| `outOfStock`, `addToCartDisabled`, `online` | | `available` |
| `labels` | `swedish_flag`, `ecological`, `keyhole` | märkning |

Kampanjer: `qualifyingCount > 1` med `rewardLabel` (`Välj & blanda! 3 för`, `35,00`) blir
`3 för 35 kr`. `qualifyingCount == 1` (`Spara 9,00 kr/st`) ger kampanjpriset
`price.value` som pris och ordinarie pris som `undiscounted`; `redeemLimitLabel`
(`Max 3 köp`) blir gränsen, så enheter över den kostar ordinarie pris. `campaignType:
LOYALTY` är Willys Plus-pris och visas så i rapporten.

## 3. Varför inte cartway direkt

cartway (github.com/oscarthroedsson/cartway, MIT, v2.0.0) granskades innan något
installerades. Den har inget verktyg för kassa, leveranstid eller betalning, och
kartlägger Willys väl. Men:

1. **Verktygen kringgår grinden före `apply`.** `set_cart_item` och `plan_apply` fyller
   varukorgen direkt. Varje agent med MCP-åtkomst kan anropa dem, utan planens
   säkerhetskontroller (tom varukorg, gränser, planens ålder) och utan användarens ja.
2. **`fetch_url`** hämtar valfri URL, med Puppeteer. Det är mer än flödet behöver.
3. **Sessionen sparas på disk** (SQLite, 24 h, i en 0700-mapp), och login-svaret från
   `/axfood/rest/customer` innehåller personnumret. Här finns sessionen bara i minnet.
4. **Webbläsaravtryck.** cartway skickar Chrome-User-Agent och NewRelic-huvuden. Här gäller
   en ärlig User-Agent med användarens kontaktadress.
5. **Beroenden:** Node, Puppeteer (laddar ner Chromium) och `better-sqlite3`.

Den egna klienten använder samma anrop men med samma regler som Mathem: en lista över
tillåtna anrop som kontrolleras före varje anrop och varje omdirigering, inga ord som
`checkout`, `slot`, `order`, `payment`, `kassa` eller `betal` i sökvägen, sessionen
bara i minnet och inloggningsuppgifter bara från `.env`.

## 4. Willys inloggning och varukorg (från cartway, ej provkört här)

Tillåtna anrop (`willys/session.py`):

| Metod | Sökväg | Till |
|---|---|---|
| GET | `/search` | sök (`q`, `size`, `page`) |
| GET | `/axfood/rest/p/<kod>` | produkt (400 = finns inte) |
| GET | `/anvandare/inloggning` | sätter cookies före inloggningen |
| POST | `/login` | inloggning |
| GET | `/axfood/rest/csrf-token` | CSRF före varukorgsanrop |
| GET | `/axfood/rest/cart` | läs varukorgen |
| POST | `/axfood/rest/cart/addProducts` | sätt antal på en rad |

- **Inloggning:** `POST /login` med `j_username`, `j_password` (varje fält krypterat som
  i Willys formulär: PBKDF2-SHA1 1000 varv → AES-128-CBC, nyckeln skickas med; det är
  förvanskning, inte sekretess), `j_remember_me`. Svaret `{"login_successful": "true"}`
  och cookien `JSESSIONID`. Ett 10-siffrigt personnummer görs om till 12 siffror.
- **Varukorg:** `addProducts` sätter **radens antal** (inte ett tillägg som hos Mathem).
  `WillysCart.add` läser därför varukorgen och skickar nuvarande antal + det nya.
  Varje POST skickar `x-csrf-token` från `csrf-token`.

### Öppna frågor till första riktiga `apply` (ägargrind)

1. Om Willys kant släpper igenom varukorgsanrop utan cartways webbläsarhuvuden. Gör den
   inte det stoppar `apply` med ett HTTP-fel innan något läggs i varukorgen.
2. Hur `_KG`-varor räknas: vi skickar antal styck (`pickUnit: pieces`). cartway säger att
   varukorgen visar vikt i gram för sådana rader; jämförelsen efteråt kan då visa en
   avvikelse som användaren kontrollerar i appen.
3. Om Willys Plus-priser (`LOYALTY`) gäller kontot.

## 5. Regler per butik

`willys-regler.yaml` är en kopia av `mathem-regler.yaml` med Willys-märkningar
(`märkning:swedish_flag`) och samma gränser. Nyckeln `köps_inte_på_mathem` heter
`köps_inte_här` i nya filer; båda läses.
