#!/usr/bin/env python3
"""Korskontrollerar en veckas handlingslista mot receptsamlingen.

Anvandning:
    validate_week.py YYYY-MM-DD/            # hela veckomappen
    validate_week.py 03-handlingslista.md 04-alla-recept.md

Kontrollerar att varje ingrediens i 04-alla-recept.md finns i
03-handlingslista.md, och att den poolade mangden racker. Skafferivaror
(salt, peppar, olja, vatten) rapporteras som TIPS, aldrig som FEL.

Exitkoder: 0 = inga FEL, 1 = minst ett FEL, 2 = anropsfel.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_recipe import (  # noqa: E402
    NUM,
    QTY_RE,
    extract_headwords,
    flip_ingredient_line,
    fold,
)

# Enheter per familj, uttryckta i en basenhet.
MASS = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "msk": 15.0, "tsk": 5.0, "krm": 1.0}
COUNT = {"st": 1.0, "": 1.0, "klyfta": 1.0, "klyftor": 1.0, "paket": 1.0, "burk": 1.0,
         "burkar": 1.0, "förp": 1.0, "knippe": 1.0, "knippen": 1.0, "kruka": 1.0,
         "krukor": 1.0, "skiva": 1.0, "skivor": 1.0}

FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75}

PANTRY = {"salt", "peppar", "svartpeppar", "vitpeppar", "olja", "olivolja",
          "rapsolja", "vatten", "socker", "strösocker", "smör"}


@dataclass
class Item:
    name: str
    amount: float | None
    family: str
    unit: str
    line_no: int


def unit_family(unit: str) -> tuple[str, float]:
    unit = unit.lower()
    for family, table in (("massa", MASS), ("volym", VOLUME), ("antal", COUNT)):
        if unit in table:
            return family, table[unit]
    return "okänd", 1.0


def parse_amount(raw: str) -> float | None:
    raw = raw.strip()
    if raw in FRACTIONS:
        return FRACTIONS[raw]
    # Intervall: anvand det ovre vardet sa att listan aldrig underskattar.
    parts = re.findall(rf"{NUM}", raw)
    if not parts:
        return None
    try:
        return max(FRACTIONS.get(p, float(p.replace(",", "."))) for p in parts)
    except ValueError:
        return None


def parse_item(line: str, line_no: int) -> Item | None:
    body = re.sub(r"^\s*[-*]\s+", "", flip_ingredient_line(line) or line).strip()
    body = re.sub(r"<!--.*?-->", "", body)
    if not body or body.startswith(("#", "|", ">")):
        return None
    qty = QTY_RE.match(body)
    if qty:
        amount = parse_amount(qty.group(0))
        unit = (qty.group(2) or "").lower()
        name = body[qty.end():]
    else:
        amount, unit, name = None, "", body
    name = re.sub(r"\([^)]*\)", " ", name).split(",")[0]
    name = re.sub(r"\s+", " ", name).strip(" ,.;:—–")
    if not name:
        return None
    family, factor = unit_family(unit)
    return Item(
        name=name,
        amount=amount * factor if amount is not None else None,
        family=family,
        unit=unit,
        line_no=line_no,
    )


def collect_recipe_items(path: Path) -> list[Item]:
    """Ingrediensrader ur 04-alla-recept.md (eller ett enskilt recept)."""
    items: list[Item] = []
    inside = False
    depth = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        heading = re.match(r"^(#{2,4})\s+(.*)$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if title.lower().startswith("ingredienser"):
                inside, depth = True, level
            elif inside and level <= depth:
                inside = False
            continue
        if inside and re.match(r"^\s*[-*]\s+\S", line):
            item = parse_item(line, line_no)
            if item:
                items.append(item)
    return items


def collect_list_items(path: Path) -> list[Item]:
    """Alla punkter i 03-handlingslista.md."""
    items: list[Item] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if re.match(r"^\s*[-*]\s+\S", line):
            item = parse_item(line, line_no)
            if item:
                items.append(item)
    return items


def keys_for(name: str) -> list[str]:
    """Jamforelsenycklar: karnord foldat till prefix."""
    out = []
    for head in extract_headwords(name):
        folded = fold(head)
        out.append(folded[:5] if len(folded) >= 5 else folded)
    return out


def cross_check(recipe_items: list[Item], list_items: list[Item]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    tips: list[str] = []

    shopping: dict[str, list[Item]] = defaultdict(list)
    for item in list_items:
        for key in keys_for(item.name):
            shopping[key].append(item)

    # Poola receptmangder per karnord och enhetsfamilj.
    pooled: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for item in recipe_items:
        keys = keys_for(item.name)
        if keys:
            pooled[(keys[0], item.family)].append(item)

    for (key, family), group in sorted(pooled.items()):
        name = group[0].name
        matches = shopping.get(key, [])
        if not matches:
            target = tips if any(fold(p).startswith(key) for p in PANTRY) else errors
            target.append(
                f"{name!r} används i recepten (rad {group[0].line_no}) men finns inte i "
                "handlingslistan. Lägg till den, eller flagga den som skafferivara."
            )
            continue

        needed = sum(i.amount for i in group if i.amount is not None)
        same_family = [i for i in matches if i.family == family and i.amount is not None]
        if not needed or not same_family:
            continue
        listed = sum(i.amount for i in same_family)
        if listed + 1e-9 < needed:
            unit = "g" if family == "massa" else "ml" if family == "volym" else "st"
            tips.append(
                f"{name!r}: recepten behöver {needed:g} {unit} men handlingslistan har "
                f"{listed:g} {unit} (rad {same_family[0].line_no}). Kontrollera poolningen."
            )

    unmatched = [
        item for item in list_items
        if not any((k, f) in pooled for k in keys_for(item.name)
                   for f in ("massa", "volym", "antal", "okänd"))
    ]
    for item in unmatched:
        tips.append(
            f"rad {item.line_no}: {item.name!r} står i handlingslistan men matchar ingen "
            "ingrediens i receptsamlingen (skafferivara, eller stavat annorlunda?)."
        )
    return errors, tips


def resolve_paths(args: list[str]) -> tuple[Path, Path] | None:
    if len(args) == 1 and Path(args[0]).is_dir():
        folder = Path(args[0])
        shopping = folder / "03-handlingslista.md"
        recipes = folder / "04-alla-recept.md"
    elif len(args) == 2:
        shopping, recipes = Path(args[0]), Path(args[1])
        if "04" in shopping.name:
            shopping, recipes = recipes, shopping
    else:
        return None
    if not shopping.is_file() or not recipes.is_file():
        missing = [str(p) for p in (shopping, recipes) if not p.is_file()]
        print(f"Saknar fil(er): {', '.join(missing)}", file=sys.stderr)
        return None
    return shopping, recipes


def main(argv: list[str]) -> int:
    paths = resolve_paths(argv)
    if paths is None:
        print(__doc__, file=sys.stderr)
        return 2
    shopping, recipes = paths

    recipe_items = collect_recipe_items(recipes)
    if not recipe_items:
        print(f"{recipes}: hittade inga ingrediensrader.", file=sys.stderr)
        return 2

    errors, tips = cross_check(recipe_items, collect_list_items(shopping))
    print(f"{shopping} ↔ {recipes}:")
    for e in errors:
        print(f"  FEL      {e}")
    for t in tips:
        print(f"  TIPS     {t}")
    if not errors and not tips:
        print("  OK       handlingslistan täcker alla ingredienser i receptsamlingen.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
