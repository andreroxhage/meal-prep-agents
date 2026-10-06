# Referens (matplanering)

## Hushållsprofil

Läs `meal-prep.local.yaml` i projektroten. Saknas den, läs `meal-prep.example.yaml`.
Värden i den lokala filen går före mallens, nyckel för nyckel, och båda går före
standardvärdena i det här dokumentet. Ett uttryckligt besked från användaren i
konversationen går före profilen.

| Nyckel | Styr |
|---|---|
| `household.portions_per_recipe` | portioner per recept när inget annat anges |
| `household.meals`, `dishes_per_week` | antal rätter och måltider i Fas 1 |
| `cook.experience` | tonen och hur mycket teknik som förklaras (se nedan) |
| `diet.allergies` | **hårda krav**: ingen rätt, inget recept och ingen vara får innehålla dem |
| `diet.avoid`, `diet.likes`, `diet.protein_focus` | urval i Fas 1 och val av recept i Fas 2 |
| `kitchen.*` | utrustning och tid i Fas 1 och Fas 5 |
| `level_mix` | förslaget när användaren inte anger veckans nivåmix |
| `pantry.always_have` | skafferi-antaganden i Fas 3 |
| `shopping.frozen_herbs_for_levels` | när bladörter köps frysta (se tabellen i `## Nivåer`) |
| `sources.extra`, `sources.avoid` | tillägg till källistan nedan |
| `integrations.*` | vilka tillval som erbjuds efter Fas 5 |

Ge subagenterna de värden de behöver i uppdraget (portioner, allergier, utrustning) —
de ska inte behöva gissa.

**Kockens erfarenhet** (`cook.experience`) ändrar tonen, inte kvalitetskravet:
- `hemmakock`: förklara tekniker kort i steget, undvik många samtidiga moment.
- `van`: precision utan förklaringar av grundtekniker.
- `yrkeskock`: proffston, prioritera teknik och kvalitet över bekvämlighet.

## Svenska receptkällor (prioritet)

**Prioritera KVALITET över bekvämlighet**, inom rättens nivå (se `## Nivåer` nedan).
Lägg till `sources.extra` och stryk `sources.avoid` från hushållsprofilen.

1. **Bästa kvalitetskällor** (svenska eller internationella):
   - Köket.se (högkvalitativa svenska recept, kocktestade)
   - Arla (särskilt för mejeridominerade rätter)
   - Mitt Kök (autentisk nordisk mat)
   - Tasteline (professionella svenska kockar)
   - Landleys Kök (högkvalitativ husmanskost)
   - Internationella källor vid autenticitetsbehov (t.ex. asiatisk mat)

2. **Sekundära källor**:
   - ICA, Coop (bra basrecept men inte prioritet)
   - Matbloggar (om kvaliteten bevisligen är hög)

3. **Sökstrategi**:
   - Jämför flera källor för varje recept
   - Prioritera recept med professionell kockbakgrund
   - Leta tekniker och smakprofiler som höjer rätten
   - Balansera kvalitet med vardagsgenomförbarhet

4. **Ge alltid klickbara länkar**

Om ingen bra källa finns för en specifik rätt: använd andra pålitliga källor och förklara kort varför.

## Nivåer

Varje rätt har en av tre nivåer. Nivån styr tid, råvarukostnad och antal moment —
inte kvalitetskravet. Kvalitet gäller inom nivån: Vardag byter dyra råvaror mot
teknik, aldrig mot tråkig mat.

| | Vardag | Standard | Avancerad |
|---|---|---|---|
| Tid (totalt, från start till tallrik) | max 30–45 min | 45–60 min | fritt, gärna helgprojekt |
| Protein | kycklinglår, kycklingfilé, hel kyckling, färs (nöt, fläsk, bland, kyckling), fläskkarré, fläskbog, fläsksida, korv, ägg, baljväxter, halloumi, billig fisk (sej, torsk, fryst lax) | allt i Vardag + färsk lax, räkor, högrev, grytbitar, lammfärs | fritt: oxfilé, entrecote, lammracks, anka, skaldjur |
| Inte i nivån | oxfilé, entrecote, ryggbiff, lammracks, hälleflundra, pilgrimsmussla, dyra ostar som bas | premiumdetaljer som huvudprotein | — |
| Komponenter | en huvudkomponent + tillbehör | 2–3 | flera, med teknikmoment (fond, emulsion, konfit, jäsning, lång marinad) |
| Numrerade steg i receptet | högst 6 | — | — |
| Bladörter (koriander, persilja, dill, gräslök, basilika) | frysta, finhackade¹ | frysta, finhackade¹ | färska |

¹ Standard. Styrs av `shopping.frozen_herbs_for_levels` i hushållsprofilen; nivåer som
inte står där får färska örter.

### Golvet för Vardag — lyftet

Varje Vardag-rätt måste ha ett namngivet **lyft**: minst ett moment som gör rätten
intressant och ryms inom tidsgränsen. Exempel:

- hemgjord sås eller dressing (pannsås, tahini, chimichurri, brynt smör)
- snabbpickles (rödlök, gurka — 10 min räcker)
- rostade eller blommade kryddor (hela kryddor i olja, egen kryddblandning)
- hård stekyta/Maillard på proteinet (i omgångar, het panna)
- färsk avslutning med syra och örter (citron, lime, vinäger, gremolata)
- krispig topping (rostade nötter/frön, stekt lök, panko i smör)

"Tacos med färdig kryddmix" klarar inte golvet. "Tacos med svartstekta kycklinglår och
snabbpicklad rödlök" gör det. Ett förslag utan lyft är ett Standard-förslag som har
förlorat sin poäng — hitta lyftet eller föreslå en annan rätt.

### Veckans nivåmix

Fråga varje vecka hur många rätter per nivå användaren vill ha. Svarar hen inte,
föreslå `level_mix` från hushållsprofilen (standard **3 Vardag + 1 Standard + 1
Avancerad**) och säg att det är ett förslag.

## Enheter & snabba konverteringar

- 1 msk = 15 ml
- 1 tsk = 5 ml
- 1 dl = 100 ml
- 10 dl = 1 l
- 1000 g = 1 kg

Praktiskt:
- Om totalsumman blir "stor", välj tydligare enhet (`1200 g` → `1,2 kg`).
- För "st"-varor: summera i `st` och lägg ev. "ca vikt" som notis om receptet kräver det.

## Normalisering av ingrediensnamn (butiksvänligt)

Använd konsekventa, vanliga namn:
- "kycklingfilé" (inte blandat med 3 varianter)
- "gul lök", "vitlök", "paprika", "morot"
- "matlagningsgrädde" vs "vispgrädde" (behåll som receptet anger)
- "ris (basmati/jasmin)" om sort spelar roll

## Skafferi-antaganden (fråga/flagga)

Gissa inte tyst. Lägg i "skafferi-antaganden" och markera som valbart. Listan är
`pantry.always_have` i hushållsprofilen; standard:
- salt, svartpeppar
- neutral olja / olivolja
- sojasås, vinäger
- buljongtärning/fond

## Handlingslista-kategorier (standard)

- Grönsaker
- Frukt
- Mejeri & Ägg
- Kött & Fisk
- Skafferi
- Kryddor & Såser
- Fryst
- Bröd
- Övrigt
