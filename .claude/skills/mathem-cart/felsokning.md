# Felsökning

| Situation | Vad det betyder | Gör så här |
| --- | --- | --- |
| Exit 0 | Klart | Fortsätt till nästa steg. |
| Exit 4 (`plan`) | Varor behöver matchning; `06-mathem-kandidater.json` är skriven | Steg 4. |
| Exit 4 (`decide`) med `Skicka om:` | Svarsfiler saknas eller är ogiltiga | Skicka ut bara de delarna igen (steg 4c), sedan `decide` igen. |
| Exit 4 (`decide`): `Omgång 2 behövs` | Nya söktermer eller osäkra varor ska bedömas en gång till | Steg 4 igen för omgång 2. |
| Exit 2 (`plan`/`decide`) | Varor behöver beslut | Steg 5, sedan `decide` igen. |
| Exit 3 (`apply`) | Säkerhetsstopp före eller direkt efter inloggning; inget tillagt | Förklara orsaken (steg 7). |
| Exit 1: `hittar inte …06-mathem-kandidater.json — kör plan först` | `decide` utan kandidatfil, men varor behöver matchning | Steg 3. |
| Exit 1: `handlingslistan har ändrats` / `har ändrats efter att den skrevs` / `stämmer inte med .mathem-matchning` / `svaren i omgång 1 har ändrats` / `omgång 2 finns redan` | Handlingslistan eller en matchningsfil ändrades efter `plan` (t.ex. skrev en agent om en fil som inte var dess svarsfil) | Kör steg 3 och hela matchningsloopen igen. |
| Varning: `omsändning.json har ändrats` | Omsändningsposten gick inte att verifiera | Inga fler omsändningar i den omgången; de delarna blir oavgjorda. Ingen åtgärd krävs. |
| Exit 1: `omgång N stöds inte` | Kandidatfilen påstår en tredje omgång | Steg 3. |
| `Varning: matchning.läge och matchning.tröskel används inte längre` | `mathem-regler.yaml` har kvar det gamla blocket `matchning` | Ingen åtgärd krävs. Föreslå att blocket tas bort ur `mathem-regler.yaml`. |
| Exit 1: `MATHEM_BOT_CONTACT saknas` | Kontaktadressen för User-Agent saknas | Användaren lägger in den i `.env`. |
| Exit 1: `03-handlingslista.md` saknas | Ingen handlingslista för veckan | Kör Fas 3 först. |
| Exit 1: `hittar inte planen` | `apply` utan plan | Kör steg 3–6. |
| Exit 1: `Inloggningen misslyckades` | Inloggningen gick inte igenom; inget tillagt | Användaren kontrollerar e-post och lösenord i `.env`. |
| Exit 1: `logga in igen / kontrollera .env` | Sessionen gick ut mitt i `apply` och en ny inloggning misslyckades | Som "Exit 1 mitt i `apply`" nedan, och kontrollera `.env`. |
| Exit 1 mitt i `apply` | Delvis ifylld varukorg | Visa `## Resultat i varukorgen`, töm varukorgen, kör `apply` igen. |
| HTTP 429 | Mathem begränsar anropen; CLI:t har redan väntat och försökt igen | Vänta några minuter och kör samma kommando igen. Sökningar cachas i `<vecka>/.mathem-cache/` i 24 h, så omkörningen upprepar inte det som redan är gjort. |
