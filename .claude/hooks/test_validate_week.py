#!/usr/bin/env python3
"""Regressionstest for korskontrollen mellan handlingslista och receptsamling.

Kor: python3 .claude/hooks/test_validate_week.py

Testerna tacker poolningen over flera recept, enhetsomvandlingen, skafferivarorna
och de tva satten att anropa skriptet (veckomapp eller filpar).
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_week import (  # noqa: E402
    collect_list_items,
    collect_recipe_items,
    cross_check,
    main,
)

failures: list[str] = []


def check(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{label}\n    förväntat: {expected!r}\n    faktiskt:  {actual!r}")


def recipe(title: str, ingredients: str) -> str:
    return f"""# Recept — {title} för 4 portioner

## Ingredienser (4 portioner)

{ingredients}

## Gör så här

### 1) Laga
- Laga maten.
"""


def week(recipes: list[str]) -> str:
    return "# Steg 4 — Alla recept\n\n---\n\n" + "\n---\n\n".join(recipes)


GRYTA = recipe("Gryta", """- 600 g kycklingfilé
- 2 dl vispgrädde
- 1 st gul lök
- 1 knippe koriander
- 1 tsk salt""")

PASTA = recipe("Pasta", """- 400 g pasta
- 2 dl vispgrädde
- 2 msk olivolja""")

LIST_OK = """# Steg 3 — Handlingslista

## Grönsaker
- 1 st gul lök

## Mejeri & Ägg
- 4 dl vispgrädde

## Kött & Fisk
- 600 g kycklingfilé

## Skafferi
- 400 g pasta

## Fryst
- 30 g koriander, fryst

---

## Skafferi-antaganden (verifiera om du har hemma)
- [ ] Salt
- [ ] Olivolja
"""


@contextlib.contextmanager
def week_folder(files: dict[str, str]) -> Iterator[Path]:
    """En tempmapp med de givna filerna."""
    with tempfile.TemporaryDirectory() as tmp:
        for name, text in files.items():
            (Path(tmp) / name).write_text(text, encoding="utf-8")
        yield Path(tmp)


def run(shopping: str, recipes: str) -> tuple[list[str], list[str]]:
    with week_folder({"03-handlingslista.md": shopping, "04-alla-recept.md": recipes}) as folder:
        return cross_check(collect_recipe_items(folder / "04-alla-recept.md"),
                           collect_list_items(folder / "03-handlingslista.md"))


def exit_code(files: dict[str, str], args: list[str]) -> int:
    """Kor main() i en tempmapp; args ar relativa till mappen."""
    with week_folder(files) as folder:
        resolved = [str(folder / a) if a != "." else str(folder) for a in args]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(resolved)


# --------------------------------------------------------------------------
# Tackning
# --------------------------------------------------------------------------

errors, tips = run(LIST_OK, week([GRYTA, PASTA]))
check("komplett lista ger inga fel", errors, [])
check("komplett lista ger inga tips", tips, [])

errors, _ = run(LIST_OK.replace("- 600 g kycklingfilé\n", ""), week([GRYTA, PASTA]))
check("saknad ingrediens ger ett fel", len(errors), 1)
check("felet namnger ingrediensen", "kycklingfilé" in errors[0] if errors else False, True)

errors, tips = run(LIST_OK, week([GRYTA]))
check("vara i listan som inget recept använder ger inget fel", errors, [])
check("vara i listan som inget recept använder ger tips", any("pasta" in t for t in tips), True)


# --------------------------------------------------------------------------
# Poolning och enheter
# --------------------------------------------------------------------------

# Tva recept x 2 dl vispgradde = 4 dl. 3 dl i listan racker inte.
errors, tips = run(LIST_OK.replace("4 dl vispgrädde", "3 dl vispgrädde"), week([GRYTA, PASTA]))
check("för liten poolad mängd ger inget fel", errors, [])
check("för liten poolad mängd ger tips", any("vispgrädde" in t and "400" in t for t in tips), True)

# Samma mangd i andra enheter: 4 dl = 0,4 l, 600 g = 0,6 kg.
converted = LIST_OK.replace("4 dl vispgrädde", "0,4 l vispgrädde").replace(
    "600 g kycklingfilé", "0,6 kg kycklingfilé")
check("l och kg räknas om", run(converted, week([GRYTA, PASTA])), ([], []))

MSK = recipe("Dressing", """- 3 msk crème fraiche
- 1 dl crème fraiche""")
check("msk och dl poolas", run("## Mejeri\n- 1,5 dl crème fraiche\n", MSK)[1], [])
check("msk och dl poolas, för lite", len(run("## Mejeri\n- 1 dl crème fraiche\n", MSK)[1]), 1)

# Intervall: ovre vardet raknas, sa listan aldrig underskattar.
RANGE = recipe("Gryta", "- 250–300 g böngroddar")
check("intervall räknas på övre värdet", len(run("## Grönsaker\n- 250 g böngroddar\n", RANGE)[1]), 1)
check("intervall täckt", run("## Grönsaker\n- 300 g böngroddar\n", RANGE), ([], []))

# Olika enhetsfamiljer jamfors inte: 1 knippe farsk mot 30 g fryst ar varken fel eller tips.
HERB = recipe("Sallad", "- 1 knippe koriander")
check("knippe mot gram jämförs inte", run("## Fryst\n- 30 g koriander, fryst\n", HERB), ([], []))

# Namnvarianter via karnord.
PLURAL = recipe("Soppa", """- 2 gula lökar
- 2 gurkor
- 3 tomater""")
check("plural matchar singular", run("## Grönsaker\n- 2 st gul lök\n- 2 st gurka\n- 3 st tomat\n", PLURAL), ([], []))
check("olika varor matchar inte", len(run("## Grönsaker\n- 2 st gul lök\n", recipe("Sås", "- 2 dl grädde"))[0]), 1)


# --------------------------------------------------------------------------
# Skafferi
# --------------------------------------------------------------------------

no_pantry = LIST_OK.split("---")[0]
errors, tips = run(no_pantry, week([GRYTA, PASTA]))
check("skafferivara som saknas ger inget fel", errors, [])
check("skafferivara som saknas ger tips", sum(("salt" in t or "olivolja" in t) for t in tips), 2)

# Bockrutorna under Skafferi-antaganden ('- [ ] Salt') raknas som tackning.
PANTRY_ONLY = recipe("Gröt", """- 2 dl vatten
- 1 tsk salt
- 2 msk olivolja""")
pantry_section = "## Skafferi-antaganden\n- [ ] Salt\n- [x] Olivolja\n"
check("skafferi-antagandena täcker salt och olja",
      [t for t in run(pantry_section, PANTRY_ONLY)[1] if "vatten" not in t], [])
errors, tips = run(pantry_section, PANTRY_ONLY)
check("vatten som saknas ger inget fel", errors, [])
check("vatten som saknas ger tips", any("vatten" in t for t in tips), True)

# Hela ordet avgor, inte nyckeln: de har borjar som en skafferivara men ar inga.
for name in ("salta jordnötter", "oliver", "vattenkastanjer", "flingsalt"):
    check(f"{name!r} som saknas ger fel", len(run("## Övrigt\n", recipe("Rätt", f"- 100 g {name}"))[0]), 1)
for name in ("salt", "olivolja", "smöret", "strösocker"):
    check(f"{name!r} som saknas ger inget fel", run("## Övrigt\n", recipe("Rätt", f"- 1 msk {name}"))[0], [])


# --------------------------------------------------------------------------
# Anrop och exitkoder
# --------------------------------------------------------------------------

good = {"03-handlingslista.md": LIST_OK, "04-alla-recept.md": week([GRYTA, PASTA])}
bad = {**good, "03-handlingslista.md": LIST_OK.replace("- 400 g pasta\n", "")}

check("veckomapp, inga fel → 0", exit_code(good, ["."]), 0)
check("veckomapp, fel → 1", exit_code(bad, ["."]), 1)
check("filpar → 0", exit_code(good, ["03-handlingslista.md", "04-alla-recept.md"]), 0)
check("filpar i omvänd ordning → 0", exit_code(good, ["04-alla-recept.md", "03-handlingslista.md"]), 0)
check("saknad fil → 2", exit_code({"04-alla-recept.md": GRYTA}, ["."]), 2)
check("inga argument → 2", exit_code({}, []), 2)
check("04 utan ingredienser → 2",
      exit_code({**good, "04-alla-recept.md": "# Steg 4\n\nInget här.\n"}, ["."]), 2)


# --------------------------------------------------------------------------

if failures:
    print(f"{len(failures)} test misslyckades:\n")
    for f in failures:
        print(f"  ✗ {f}")
    sys.exit(1)

print("Alla test godkända.")
