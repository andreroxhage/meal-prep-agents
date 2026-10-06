---
paths:
  - "recipe/**/*.md"
  - "**/recept-*.md"
  - "**/04-alla-recept.md"
  - "**/05-meal-prep-plan.md"
---

# Receptstandard (obligatorisk)

Alla receptfiler följer denna standard. Den kontrolleras maskinellt av
`.claude/hooks/validate_recipe.py` efter varje `Write`/`Edit` — avvikelser skickas
tillbaka som fel som ska rättas, inte förklaras bort.

Se `.claude/rules/recipe-examples.md` för kompletta exempel och bra/dåligt-par.

Ett recept läses i tre lägen, och standarden ska bära alla tre:

| Läge | Frågan läsaren har | Regler som svarar |
|---|---|---|
| Inköp | Hur mycket behöver jag totalt? | Regel 3, Regel 4a |
| Planering | När börjar jag med vad? | Regel 4b, Regel 7 |
| Utförande | Vad gör jag nu, och gick det rätt? | Regel 1, Regel 5, Regel 6, Regel 8 |

## Regel 1 — mängden står i instruktionen (viktigast)

Läsaren står vid spisen och scrollar inte tillbaka till ingredienslistan.
**Första gången en ingrediens används i ett steg ska mängden stå med i steget**,
fetmarkerad:

- ✅ `Häll **1,5 dl** mjölk över **1 dl** ströbröd och låt svälla 10 min.`
- ❌ `Häll mjölken över ströbrödet och låt svälla 10 min.`

Senare hänvisningar till samma ingrediens behöver ingen mängd
(`Rör ner brödblandningen i färsen`).

Undantag — ingrediensen behöver ingen mängd i steget om ingredienslistan anger
`efter smak`, `valfritt`, `till servering`, `till stekning` eller `att servera till`.
Behövs undantag i övriga fall: sätt `<!-- no-qty: [kort motivering] -->` sist på
ingrediensraden.

## Regel 2 — varje ingrediens används

Varje ingrediens i listan ska nämnas i minst ett steg. Ingredienser som inte
används är antingen bortglömda i instruktionen eller överblivna från skalning.

## Regel 3 — ingrediensrader

Format: `- <mängd> <enhet> <ingrediens> (<ev. förberedelse>)` — mängden först.

```
- 1,5 dl mjölk
- 800 g blandfärs (50/50 nöt och fläsk)
- 1 gul lök (finriven)
- salt och svartpeppar efter smak
```

- **Mängd först**, inte `- Mjölk — 1,5 dl`.
- **Decimalkomma**, inte punkt: `1,2 kg` — aldrig `1.2 kg`.
- **Mellanslag mellan siffra och enhet**: `28 g` — aldrig `28g`.
- **Bråk som tecken**: `½`, `¼`, `¾` — inte `1/2`.
- **Intervall med tankstreck**: `1,6–1,8 kg`, `4–5 min`.
- **Tillåtna enheter**: g, kg, ml, cl, dl, l, msk, tsk, krm, st, klyfta/klyftor,
  knippe, kvist/kvistar, näve, nypa, paket, burk, förp, skiva/skivor, kruka.
- **Normalisera**: `1000 g` → `1 kg`, `10 dl` → `1 l`, `100 cl` → `1 l`.

## Regel 4 — filstruktur

Exakt dessa rubriker, i denna ordning. Rubriker märkta *(valfri)* utelämnas när
receptet inte behöver dem — ett vardagsrecept på 20 minuter använder ingen av dem.

```markdown
# Recept — <Rättens namn> för <X> portioner

**<X portioner> · ca <aktiv tid> · <kalendertid om den skiljer sig>**   (valfri)

<1–2 meningar om rätten och vad som gör den bra>

## Ingredienser (<X> portioner)

### Totalt att handla                                  (valfri — se 4a)

| Vara | Totalt | Varav |
| --- | --- | --- |
| <råvara> | <summa> | <fördelning per del> |

### <Kategori, t.ex. Bas / Protein / Sås / Tillbehör>
- <ingrediensrader enligt Regel 3>

## Gör så här

### Dag N — <när> · ca <tid> aktivt                    (valfri — se 4b)

#### 1) <Stegrubrik>
- <instruktion enligt Regel 1>

#### 2) <Stegrubrik>
- ...

## Matlåda / förvaring
- Kyl: <hållbarhet>
- Frys: <hållbarhet + tips>
- Uppvärmning: <bästa metod>

## Noter                                               (valfri — se 4c)

### <Variant, bakgrund eller fördjupning>

## Källor
- <källnamn>: <URL>
```

Portionsantalet i `# Recept — ... för X portioner`, i `## Ingredienser (X portioner)`
och i filnamnets `-<X>p.md` ska vara samma tal.

Utan dagsgruppering är stegen `### 1)`, `### 2)` direkt under `## Gör så här`.

### 4a — `### Totalt att handla`

**Obligatorisk när samma råvara förekommer i två eller fler dellistor** — vetemjöl i
både deg och fyllning, smör i både deg och sås, ägg i både smet och pensling. Annars
utelämnas den.

Dellistorna är receptets *delar*, inte varor. Det är gratis så länge varje råvara
förekommer en gång; då är dellistorna redan totalen. Så fort en råvara delas mellan
delar finns totalen ingenstans, och läsaren som ska handla får addera för hand.

Totalen är **en tabell, aldrig en punktlista**. En punktlista skulle upprepa
ingredienserna som riktiga ingrediensrader, och då börjar Regel 2 jämföra motstridiga
mängder mot stegen. Tabellen är avsiktligt osynlig för kontrollen.

Dellistorna står kvar oförändrade under tabellen — de behövs vid utförandet.

### 4b — dagsgruppering

**Används när receptet sträcker sig över mer än ett pass** — kalljäsning över natten,
marinering ett dygn, allt som har en kalendergräns mitt i sig. Grupperingen är
`### Dag N — <när> · ca <tid> aktivt`, och stegen blir `#### N)`.

**Numreringen löper obrutet över dagsgränsen.** Dag 2 börjar på steg 5 om dag 1
slutade på steg 4, så att korsreferenser (`grädda enligt steg 8`) håller.

Passiv tid är inte ett steg. Den hör till steget som startar den (`ställ i kyl vid
4 °C i 12–24 timmar`) och sammanfattas i tidsraden under H1.

### 4c — `## Noter`

**Ett numrerat steg är något du gör, en gång, i tur och ordning.**

Allt annat hör hemma i `## Noter`: varianter och alternativ, bakgrund och teknik,
utbyten, fördjupning, källkritik. Utan det facket blir de numrerade steg — och ett
alternativ som ligger som steg 9 läses som något du gör efter steg 8, vilket är fel.

Tidsplaner hör inte till Noter. De hör till tidsraden under H1 och till
dagsrubrikerna, eftersom de behövs innan man börjar läsa stegen.

### 4d — ingressen skrivs med `no-ai-slop`

De 1–2 meningarna under H1 är den enda löptexten som säljer rätten, och det är där
AI-tonen syns först ("en klassiker som aldrig sviker", "perfekt för en mysig
vardagskväll"). Skriv ett utkast och redigera det sedan med skillen **`no-ai-slop`**
(`.claude/skills/no-ai-slop/`), inklusive dess `eval.md`, innan filen sparas. Är
skillen förladdad i din agent följer du den direkt.

Skillen gäller **bara ingressen**. Mängder, ingrediensrader, steg och rubriker rörs
inte; de styrs av reglerna här. Ingressen ska fortfarande säga något konkret om rätten:
tekniken, råvaran eller valet som gör den bra (se Exempel A och B).

Skillen är skriven på engelska. Det här är vad den behöver veta här, så att den inte
behöver fråga:

- **Läsare:** en van kock som lagar maten hemma (se `cook.experience` i hushållsprofilen). Texten är på svenska.
- **Mönstren gäller på svenska.** Ordlistan är engelsk, men mönstren är desamma:
  "lyfter smakerna", "en riktig klassiker", "perfekt för", "det här är inte bara X,
  det är Y", "hemligheten är". Stryk dem och säg vad som faktiskt händer i grytan.
- **Inget tankstreck som rytm** i ingressen. Tankstreck i intervall (`4–5 min`) är
  något annat och står kvar.
- **"What changed"** hör till din rapport, inte till receptfilen.

## Regel 5 — instruktionernas innehåll

- **Konkret, inte vagt**: `Stek på medelhög värme 4–5 min tills gyllenbrun`,
  inte `stek tills klart`.
- **Temperaturer i °C**, alltid. Ange innertemperatur för kött (`till 68 °C i mitten`).
- **Tider i minuter/timmar**, alltid specifika.
- **Proffston**: skriv som en kock, inte som en matblogg. Inga tomma ord.
- **Svenska** genomgående.

### 5a — skriv ut det som ser fel ut

Går momentet igenom ett läge där resultatet **ser misslyckat ut fast det är rätt**, ska
steget säga det rakt ut, och säga vad som får det att gå över:

- ✅ `Degen blir slipprig och smöret smetar längs bunkens kant — så ska det se ut.
  Den samlar ihop sig igen efter 8–10 min knådning.`
- ❌ `Knåda vidare 8–10 min tills degen släpper bunkens kant helt.`

Det andra är inte fel, men det beskriver bara **slutläget**. Läsaren som står i
mellanläget ser en deg som skär sig och drar slutsatsen att något gått snett — oftast
att en mängd blev fel. Då avbryts eller "räddas" ett moment som var på väg att lyckas,
och räddningen (mer mjöl, mer värme, mer vispning) är det som faktiskt förstör satsen.

Klassiska lägen som kräver den här meningen: smör som arbetas in i färdigknådad deg,
emulsioner som skär sig innan de går ihop, smet som sjunker efter första vändningen,
såser som separerar innan de reds, deg som är avsiktligt lösare än läsaren väntar sig.

### 5b — kontrollen står där tvivlet uppstår

Finns en mätning som avgör om momentet gick rätt — degtemperatur, innertemperatur,
konsistens, pH — ska den stå **i det stycke där det kan gå fel**, inte som sista raden
i steget.

En kontroll som står sist besvarar frågan efter att läsaren redan hunnit fatta sitt
beslut. `Mät degtemperaturen: målet är 24–25 °C` är rätt information på fel plats om
den står efter smörinarbetningen i stället för i den.

Skriv kontrollen som ett utfall med åtgärd, inte bara ett måltal:

- ✅ `Mät degtemperaturen innan smöret går i: under 26 °C fortsätter du, över 27 °C
  ställer du bunken kallt 15 min först. Varmare än så smälter smöret ut i stället
  för att emulgera.`
- ❌ `Degtemperaturen ska vara 24–25 °C.`

## Regel 6 — mängden i steget är den du faktiskt tar

En fetmarkerad mängd i ett steg läses som **"det här ska i bunken nu"**. Är den i
själva verket totalmängden för flera omgångar, eller för hela satsen när steget bara
gäller en del av den, har Regel 1 gjort receptet farligare i stället för säkrare.

Körs ett steg i omgångar, eller gäller det bara en del av satsen, ska **mängden per
omgång stå först** och totalen stå som referens:

- ✅ `Tillsätt **200 g** smör (halva listans 400 g — du kör det här steget två gånger).`
- ❌ `Halvera varje mängd i det här steget.` … `Tillsätt **400 g** smör.`

Samma sak när en ingrediens delas mellan två steg: skriv `**220 g** av fyllningen (en
fjärdedel)`, inte `fyllningen`.

Ett steg som säger "halvera" och sedan listar totalmängderna kräver att läsaren
räknar om sju tal i huvudet, mitt i momentet, med händerna i degen. Det är precis då
felet sker — och ett dubbeldoserat fett eller salt märks inte förrän satsen är
förstörd.

## Regel 7 — beslut står före steget de påverkar

Ändrar en variant en mängd eller ett moment, ska den flaggas **senast i det steg där
mängden först används**, inte där varianten råkar beskrivas.

- Ett alternativ som byter jästmängd hör till steget där jästen vägs upp — inte till
  jäsningssteget två steg senare.
- Ett val mellan två ytor (pärlsocker eller sirapslag) hör till steget där ytan läggs
  på — inte som ett eget steg efteråt.
- Ett val som avgör hur mycket som ska tillagas nu och hur mycket som fryses hör till
  steget där satsen delas.

Beskrivningen av varianten ligger i `## Noter`; **pekaren** till den ligger i steget,
eller i en kort valruta först under `## Gör så här` när valet gäller hela receptet.

## Regel 8 — handlingen först, detaljer efter

Läsaren har flera kastruller igång och tittar upp från spisen för att hitta nästa
moment. Varje punkt börjar därför med **vad du gör och hur**: verbet, mängden,
värmen, tiden och hur du ser att det är klart. Den som har bråttom läser första
meningen och går vidare. Den som vill förstå läser vidare.

- **Första meningen är handlingen**, högst 25 ord utöver mängderna. Kontrollen
  tipsar om längre.
- **Detaljerna kommer efter**, i nästa mening: varför, vad som ser fel ut men är
  rätt (Regel 5a), tips. De får gärna stå kvar, så länge de inte står först.
- **Inget varför före hur.** En förklaring mitt i handlingen skjuter värmen och
  tiden till slutet av meningen, där läsaren inte hinner fram.
- **Fyllnad stryks**: "ingen brådska här" och "kritiskt för djupet" säger inget som
  tiden och klartecknet inte redan säger.
- **Vardag:** detaljmeningar bara där risken finns. Antalet steg per nivå står i
  `## Nivåer` i `.claude/skills/meal-planning-hello-fresh/reference.md`.

- ✅ `Stek **800 g** kycklinglår i två omgångar på hög värme, 4 min per sida, till
  72 °C. Vänd dem inte förrän de släpper pannan, då har stekytan bildats.`
- ❌ `Stek **800 g** kycklinglår i två omgångar så att de får ordentlig stekyta istället
  för att koka i sin egen vätska — det är här smaken byggs, så ha tålamod och vänd
  inte för tidigt, 4 min per sida.`

## Filnamn

`recept-<namn-med-bindestreck>-<portioner>p.md`, t.ex. `recept-kycklingfajitas-6p.md`.
