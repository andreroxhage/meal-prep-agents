#!/usr/bin/env python3
"""Validerar receptfiler mot .claude/rules/recipe-style.md.

Anvandning:
    validate_recipe.py [--fix] FIL...

--fix normaliserar mekaniska fel (decimalkomma, mellanslag fore enhet, brak,
intervall, enhetsnormalisering) direkt i filen och rapporterar vad som andrades.

Exitkoder: 0 = inga FEL, 1 = minst ett FEL, 2 = anropsfel.

Rapporten ar avsedd att lasas av Claude via en PostToolUse-hook, darfor ar den
skriven pa svenska och namnger alltid rad, ingrediens och atgard.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

UNITS = [
    "kg", "g", "ml", "cl", "dl", "l", "msk", "tsk", "krm", "st",
    "klyftor", "klyfta", "knippen", "knippe", "nypor", "nypa", "nävar", "näve",
    "paket", "burkar", "burk", "förp", "skivor", "skiva", "krukor", "kruka",
    "kvistar", "kvist",
]
UNIT_RE = "|".join(sorted(UNITS, key=len, reverse=True))

NUM = r"(?:\d+(?:[,.]\d+)?|[½¼¾])"
QTY_RE = re.compile(rf"({NUM})(?:\s*[–-]\s*{NUM})?\s*(?:\*\*)?\s*({UNIT_RE})?\b", re.IGNORECASE)

# Ord som aldrig ar ingrediensens karnord: bindeord, matt-ord och beredningsord.
FILLER = {
    # bindeord och matt-ord
    "ca", "à", "av", "och", "till", "för", "i", "en", "ett", "eller", "med",
    "bit", "bitar", "konsistens", "behov", "smak", "klyftor", "klyfta", "påse",
    "burk", "paket", "handfull", "nypa", "näve", "knippe", "kruka",
    # storlek och farg
    "stor", "stora", "liten", "litet", "små", "hel", "helt", "hela", "tunn",
    "tunna", "tunt", "gul", "gula", "röd", "röda", "grön", "gröna", "vit", "vita",
    # beredning
    "färsk", "färska", "färskt", "finhackad", "finhackade", "hackad", "hackade",
    "grovhackad", "grovhackade", "riven", "rivna", "rivet", "strimlad",
    "strimlade", "finstrimlad", "finstrimlade", "skivad", "skivade", "pressad",
    "pressat", "kokt", "kokta", "okokt", "nymalen", "malen", "benfri", "torkad",
    "torkade", "rostad", "rostade", "fryst", "frysta", "urkärnad", "valfritt",
    "gärna", "delad", "delade", "halverad", "halverade",
}

# Ingredienser med dessa fraser behover ingen mangd i steget.
NO_QTY_PHRASES = (
    "efter smak", "efter behov", "valfritt", "till servering", "till stekning",
    "att servera till", "till garnering", "till pensling", "att toppa med",
)

VAGUE = ("tills klart", "tills klar", "tills färdig", "tills det är klart", "lagom länge")

TIME_TEMP_AFTER = re.compile(
    r"\s*(?:°|grader|min\b|minut|timm|tim\b|h\b|sek|portioner|%)", re.IGNORECASE
)


def fold(word: str) -> str:
    """Ta bort diakriter sa att 'morötter' och 'moroten' delar prefix."""
    stripped = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


@dataclass
class Ingredient:
    line_no: int
    raw: str
    name: str
    amount: str
    headwords: list[str]
    has_number: bool
    skip_qty: bool
    skip_all: bool
    group: str = ""


@dataclass
class Report:
    path: Path
    errors: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def tip(self, msg: str) -> None:
        self.tips.append(msg)

    def render(self) -> str:
        out = [f"{self.path}:"]
        for f in self.fixes:
            out.append(f"  RÄTTAT   {f}")
        for e in self.errors:
            out.append(f"  FEL      {e}")
        for t in self.tips:
            out.append(f"  TIPS     {t}")
        return "\n".join(out)


# --------------------------------------------------------------------------
# Mekanisk normalisering (--fix)
# --------------------------------------------------------------------------

def _skip_line(line: str) -> bool:
    return "http" in line or line.lstrip().startswith("```")


def normalize(text: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    lines = text.split("\n")
    in_code = False
    # Vandningen av '- Namn — mangd' far bara rora ingredienssektionen. En
    # instruktionspunkt som '- Lagg 12 per plat — 24 bullar blir 2 platar' ser
    # likadan ut for regexen och blev tidigare sonderskriven. Default True sa att
    # normalize() pa en losryckt rad (utan rubriker) fortfarande vander den.
    in_ingredients = True

    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or _skip_line(line):
            continue
        if re.match(r"^##\s+\S", line):
            in_ingredients = bool(re.match(r"^##\s+Ingredienser", line))
        original = line

        # 1,2 kg — decimalkomma istallet for punkt
        line = re.sub(rf"(\d)\.(\d)(?=\s*(?:{UNIT_RE})\b)", r"\1,\2", line, flags=re.IGNORECASE)

        # ½ istallet for 1/2 — gors fore fetmarkeringsfixen nedan sa att
        # '**1/2 dl**strobrod' blir helt normaliserad i samma svep.
        for frac, char in (("1/2", "½"), ("1/4", "¼"), ("3/4", "¾")):
            line = line.replace(frac, char)

        # 28 g — mellanslag mellan siffra och enhet
        line = re.sub(rf"(\d)({UNIT_RE})\b", r"\1 \2", line)

        # **1 dl** mjölk — mellanslag efter fetmarkerad mängd.
        # Monstret ar avsiktligt snavt: bara en fetmarkering som innehaller en
        # mangd. Ett bredare monster parar ihop avslutande ** i en fetmarkering
        # med inledande ** i nasta och stoppar in mellanslag mitt i texten.
        line = re.sub(
            rf"\*\*(\s*{NUM}(?:\s*[–-]\s*{NUM})?\s*(?:{UNIT_RE})?\s*)\*\*(\w)",
            r"**\1** \2",
            line,
            flags=re.IGNORECASE,
        )

        # 4–5 min — tankstreck i intervall. Grannvillkoren utesluter datum:
        # i '2026-06-08' foljs eller foregas varje kandidat av siffra/bindestreck.
        line = re.sub(r"(?<![\d-])(\d+)\s*-\s*(\d+)(?![\d-])", r"\1–\2", line)

        # 180 °C — mellanslag fore gradtecken
        line = re.sub(r"(\d)\s*°C", r"\1 °C", line)

        # Enhetsnormalisering: 1000 g -> 1 kg, 10 dl -> 1 l, 100 cl -> 1 l
        def unit_norm(m: re.Match[str]) -> str:
            val, unit = m.group(1), m.group(2).lower()
            try:
                num = float(val.replace(",", "."))
            except ValueError:
                return m.group(0)
            table = {"g": (1000, "kg"), "ml": (1000, "l"), "cl": (100, "l"), "dl": (10, "l")}
            if unit not in table:
                return m.group(0)
            factor, target = table[unit]
            if num >= factor and num % factor == 0:
                new = int(num // factor)
                return f"{new} {target}"
            return m.group(0)

        line = re.sub(rf"\b(\d+(?:,\d+)?)\s+({UNIT_RE})\b", unit_norm, line)

        # "- Mjölk — 1,5 dl" -> "- 1,5 dl mjölk"
        if in_ingredients:
            flipped = flip_ingredient_line(line)
            if flipped is not None:
                line = flipped

        if line != original:
            fixes.append(f"rad {i + 1}: {original.strip()!r} → {line.strip()!r}")
            lines[i] = line

    return "\n".join(lines), fixes


def flip_ingredient_line(line: str) -> str | None:
    """Vand '- Namn — mangd' till '- mangd namn'. None om raden inte matchar."""
    m = re.match(r"^(\s*[-*]\s+)([^—–]+?)\s+[—–]\s+(.+?)\s*$", line)
    if not m:
        return None
    indent, name, right = m.groups()
    qty = re.match(rf"^({NUM}(?:\s*[–-]\s*{NUM})?(?:\s+(?:{UNIT_RE}))?)\s*(.*)$", right, re.IGNORECASE)
    if not qty:
        return None
    amount, rest = qty.group(1).strip(), qty.group(2).strip()
    name = name.strip()
    # Gemener bara om namnet inte ser ut som ett egennamn.
    if name[1:] == name[1:].lower():
        name = name[0].lower() + name[1:]
    tail = f" {rest}" if rest else ""
    return f"{indent}{amount} {name}{tail}"


# --------------------------------------------------------------------------
# Struktur
# --------------------------------------------------------------------------

def check_structure(path: Path, lines: list[str], rep: Report) -> int | None:
    text = "\n".join(lines)
    portions: int | None = None

    h1 = re.search(r"^#\s+Recept\s+—\s+(.+?)\s+för\s+(\d+)\s+portioner\s*$", text, re.M)
    if not h1:
        rep.error(
            "saknar korrekt H1. Första raden ska vara "
            "'# Recept — <Rättens namn> för <X> portioner' (Regel 4)."
        )
    else:
        portions = int(h1.group(2))

    ing = re.search(r"^##\s+Ingredienser\s*\((\d+)\s+portioner\)\s*$", text, re.M)
    if not ing:
        rep.error("saknar rubriken '## Ingredienser (<X> portioner)' (Regel 4).")
    elif portions is not None and int(ing.group(1)) != portions:
        rep.error(
            f"portionsantalet skiljer: H1 säger {portions}, "
            f"'## Ingredienser' säger {ing.group(1)} (Regel 4)."
        )

    for heading, label in (
        (r"^##\s+Gör så här\s*$", "## Gör så här"),
        (r"^##\s+Matlåda", "## Matlåda / förvaring"),
        (r"^##\s+Källor", "## Källor"),
    ):
        if not re.search(heading, text, re.M):
            rep.error(f"saknar rubriken '{label}' (Regel 4).")

    fn = re.search(r"-(\d+)p\.md$", path.name)
    if fn and portions is not None and int(fn.group(1)) != portions:
        rep.error(
            f"filnamnet säger {fn.group(1)} portioner men receptet säger {portions}. "
            "Byt namn på filen eller rätta rubrikerna (Regel 4)."
        )
    elif not fn:
        rep.tip(
            f"filnamnet följer inte 'recept-<namn>-<portioner>p.md' "
            f"(nu: {path.name})."
        )

    order = [
        (m.start(), name)
        for name, pattern in (
            ("Ingredienser", r"^##\s+Ingredienser"),
            ("Gör så här", r"^##\s+Gör så här"),
            ("Matlåda", r"^##\s+Matlåda"),
            ("Noter", r"^##\s+Noter"),
            ("Källor", r"^##\s+Källor"),
        )
        for m in [re.search(pattern, text, re.M)]
        if m
    ]
    if order != sorted(order):
        rep.error(
            "rubrikerna ligger i fel ordning. Ordningen ska vara Ingredienser → "
            "Gör så här → Matlåda / förvaring → Noter (valfri) → Källor (Regel 4)."
        )
    return portions


# --------------------------------------------------------------------------
# Ingredienser och steg
# --------------------------------------------------------------------------

def section_bounds(lines: list[str], pattern: str) -> tuple[int, int] | None:
    start = None
    for i, line in enumerate(lines):
        if re.match(pattern, line):
            start = i + 1
            continue
        if start is not None and re.match(r"^##\s+\S", line):
            return start, i
    return (start, len(lines)) if start is not None else None


def subsection_map(lines: list[str], bounds: tuple[int, int]) -> dict[int, str]:
    """Radnummer (1-indexerat) -> narmaste foregaende '### '-rubrik i sektionen."""
    out: dict[int, str] = {}
    current = ""
    for idx in range(*bounds):
        heading = re.match(r"^###\s+(.+?)\s*$", lines[idx])
        if heading:
            current = heading.group(1).strip()
        out[idx + 1] = current
    return out


def parse_ingredients(lines: list[str], rep: Report) -> list[Ingredient]:
    bounds = section_bounds(lines, r"^##\s+Ingredienser")
    if not bounds:
        return []
    groups = subsection_map(lines, bounds)
    out: list[Ingredient] = []
    for line_no, line in list_items(lines, bounds, r"^[-*]\s+\S"):
        idx = line_no - 1
        body = re.sub(r"^\s*[-*]\s+", "", line).strip()
        lowered = body.lower()
        skip_all = "<!-- no-check" in lowered
        skip_qty = skip_all or "<!-- no-qty" in lowered or any(p in lowered for p in NO_QTY_PHRASES)
        body_clean = re.sub(r"<!--.*?-->", "", body).strip()

        qty = QTY_RE.match(body_clean)
        has_number = bool(qty)
        amount = qty.group(0).strip() if qty else ""
        name = body_clean[qty.end():].strip() if qty else body_clean
        # Parenteser och allt efter forsta kommat ar beredning, inte namn.
        name = re.sub(r"\([^)]*\)", " ", name).split(",")[0]
        name = re.sub(r"\s+", " ", name).strip(" ,.;:")

        if not name:
            rep.tip(f"rad {idx + 1}: kunde inte läsa ut något ingrediensnamn ur {body!r}.")
            continue

        headwords = extract_headwords(name)
        if not headwords:
            continue

        unit = (qty.group(2) or "").lower() if qty else ""
        if unit and unit not in UNITS:
            rep.tip(f"rad {idx + 1}: enheten {unit!r} finns inte i den tillåtna listan (Regel 3).")

        out.append(
            Ingredient(
                line_no=idx + 1,
                raw=body,
                name=name,
                amount=amount,
                headwords=headwords,
                has_number=has_number,
                skip_qty=skip_qty,
                skip_all=skip_all,
                group=groups.get(idx + 1, ""),
            )
        )
    return out


def extract_headwords(name: str) -> list[str]:
    """Karnord att leta efter i stegen — ett per alternativ ('sriracha/chili')."""
    heads: list[str] = []
    for alternative in re.split(r"\s*/\s*|\s+eller\s+", name.lower()):
        words = [w.strip(" ,.;:") for w in alternative.split()]
        content = [w for w in words if w and w not in FILLER]
        if content:
            heads.append(content[0])
        elif words:
            heads.append(words[0])
    return [h for h in heads if h]


def list_items(lines: list[str], bounds: tuple[int, int], marker: str) -> list[tuple[int, str]]:
    """Plocka ut listpunkter och slå ihop radbrutna fortsättningsrader."""
    items: list[tuple[int, str]] = []
    for idx in range(*bounds):
        line = lines[idx]
        if re.match(marker, line.strip()):
            items.append((idx + 1, line.strip()))
        elif items and line.strip() and not re.match(r"^#|^```", line.strip()):
            # Indragen fortsättning på föregående punkt.
            if line.startswith((" ", "\t")):
                line_no, text = items[-1]
                items[-1] = (line_no, f"{text} {line.strip()}")
    return items


def parse_steps(lines: list[str]) -> list[tuple[int, str]]:
    bounds = section_bounds(lines, r"^##\s+Gör så här")
    if not bounds:
        return []
    return list_items(lines, bounds, r"^([-*]|\d+[.)])\s+\S")


def qty_near(step: str, pos: int) -> tuple[bool, bool]:
    """Finns en mangd nara ingrediensen? Returnerar (finns, ar_fetmarkerad)."""
    window_start = max(0, pos - 45)
    window = step[window_start: pos + 25]
    for m in QTY_RE.finditer(window):
        after = window[m.end(): m.end() + 8]
        if TIME_TEMP_AFTER.match(after):
            continue
        abs_start = window_start + m.start()
        bolded = bool(re.search(r"\*\*[^*]*$", step[:abs_start])) or step[
            max(0, abs_start - 2): abs_start
        ] == "**"
        return True, bolded
    return False, False


def find_mention(step: str, headwords: list[str]) -> int | None:
    """Position for forsta omnamnandet, eller None.

    Matchar pa prefix efter diakritfoldning sa att bojningar traffar
    ('lök' → 'löken', 'morötter' → 'moroten'). For sammansatta ord matchas
    ocksa efterledet, sa att 'jasminris' hittas i 'riset' och 'svartpeppar'
    i 'peppar'.
    """
    words = [(m.start(), fold(m.group(0))) for m in re.finditer(r"[A-Za-zÀ-öø-ÿ]+", step)]
    for headword in headwords:
        folded = fold(headword)
        candidates = [folded[:5] if len(folded) >= 5 else folded]
        if len(folded) >= 6:
            # Efterled i sammansatta ord, langst forst.
            candidates += [folded[i:] for i in range(1, len(folded) - 2)]
        for cand in candidates:
            if len(cand) < 3:
                continue
            for pos, word in words:
                if word.startswith(cand):
                    return pos
    return None


def check_amounts(ingredients: list[Ingredient], steps: list[tuple[int, str]], rep: Report) -> None:
    if not steps:
        rep.error("hittar inga instruktionssteg under '## Gör så här' (Regel 4).")
        return
    for ing in ingredients:
        if ing.skip_all:
            continue
        first: tuple[int, str, int] | None = None
        for line_no, step in steps:
            pos = find_mention(step, ing.headwords)
            if pos is not None:
                first = (line_no, step, pos)
                break

        if first is None:
            rep.error(
                f"rad {ing.line_no}: ingrediensen {ing.name!r} nämns inte i något steg "
                "(Regel 2). Namnge den i det steg där den används — 'blanda alla "
                "ingredienser' räcker inte. Stryk raden om den inte hör hit, eller lägg "
                "'<!-- no-check -->' sist på raden om den avsiktligt bara serveras till."
            )
            continue

        if ing.skip_qty or not ing.has_number:
            continue

        line_no, step, pos = first
        present, bolded = qty_near(step, pos)
        example = f"**{ing.amount}** {ing.name}" if ing.amount else f"**mängd** {ing.name}"
        if not present:
            rep.error(
                f"rad {line_no}: steget använder {ing.name!r} utan mängd. Skriv in "
                f"mängden från rad {ing.line_no} i steget: '{example}' (Regel 1)."
            )
        elif not bolded:
            rep.tip(
                f"rad {line_no}: mängden för {ing.name!r} står i steget men är inte "
                f"fetmarkerad. Skriv '{example}' (Regel 1)."
            )


# Skafferivaror handlas inte per recept, sa de motiverar ingen totaltabell.
# Samma avgransning som CLAUDE.md gor for handlingslistan.
PANTRY = {fold(w) for w in (
    "salt", "flingsalt", "havssalt", "peppar", "svartpeppar", "vitpeppar",
    "vatten", "olja", "olivolja", "rapsolja", "matolja",
)}


def check_totals_table(lines: list[str], ingredients: list[Ingredient], rep: Report) -> None:
    """Delas en ravara mellan dellistor behovs '### Totalt att handla' (Regel 4a)."""
    bounds = section_bounds(lines, r"^##\s+Ingredienser")
    if not bounds:
        return
    if any(re.match(r"^###\s+Total", lines[i], re.IGNORECASE) for i in range(*bounds)):
        return
    if len({ing.group for ing in ingredients if ing.group}) < 2:
        return

    spread: dict[str, tuple[str, set[str]]] = {}
    for ing in ingredients:
        if not ing.group:
            continue
        for head in ing.headwords:
            if fold(head) in PANTRY:
                continue
            display, groups = spread.setdefault(fold(head), (head, set()))
            groups.add(ing.group)

    shared = sorted(display for display, groups in spread.values() if len(groups) > 1)
    if not shared:
        return
    listed = ", ".join(shared[:4]) + (" m.fl." if len(shared) > 4 else "")
    noun = "råvara" if len(shared) == 1 else "råvaror"
    rep.tip(
        f"{len(shared)} {noun} förekommer i flera dellistor ({listed}). Då finns "
        "totalmängden ingenstans och läsaren får addera för hand — lägg till "
        "'### Totalt att handla' som tabell först under '## Ingredienser' (Regel 4a)."
    )


# Stegrubriker som beskriver nagot annat an ett moment i sekvensen.
NON_STEP = re.compile(
    r"^not\b|\b(alternativ|i stället för|istället för|tidsplan|bakgrund|varför)\b",
    re.IGNORECASE,
)

# Steg som kors om i omgangar — da ar en fetmarkerad totalmangd vilseledande.
BATCH_TRIGGER = re.compile(
    r"halvera\w*\s+(?:varje|alla|samtliga)\s+mängd"
    r"|kör momentet (?:två|tre) gånger"
    r"|dela satsen",
    re.IGNORECASE,
)
BATCH_RESOLVED = re.compile(r"\bper omgång\b|\bvarje omgång\b|\bper sats\b", re.IGNORECASE)


def check_step_shape(lines: list[str], rep: Report) -> None:
    bounds = section_bounds(lines, r"^##\s+Gör så här")
    if not bounds:
        return

    for idx in range(*bounds):
        heading = re.match(r"^#{3,4}\s*\d+\)\s*(.+?)\s*$", lines[idx])
        if heading and NON_STEP.search(heading.group(1)):
            rep.tip(
                f"rad {idx + 1}: steget {heading.group(1)!r} ser ut att vara en variant, "
                "en tidsplan eller bakgrund snarare än ett moment. Ett numrerat steg är "
                "något du gör, en gång, i tur och ordning — flytta resten till "
                "'## Noter' (Regel 4c)."
            )

    body = "\n".join(lines[bounds[0]: bounds[1]])
    if BATCH_TRIGGER.search(body) and not BATCH_RESOLVED.search(body):
        rep.tip(
            "ett steg körs i omgångar men ingen mängd anges per omgång. En fetmarkerad "
            "mängd läses som 'det här ska i bunken nu' — skriv mängden du faktiskt tar "
            "först och totalen som referens (Regel 6)."
        )


def check_prose(lines: list[str], rep: Report) -> None:
    text = "\n".join(lines)
    for phrase in VAGUE:
        for m in re.finditer(re.escape(phrase), text, re.IGNORECASE):
            line_no = text[: m.start()].count("\n") + 1
            rep.tip(
                f"rad {line_no}: {phrase!r} är vagt. Ange tid, temperatur eller ett "
                "visuellt tecken istället (Regel 5)."
            )
    if re.search(r"\b(ugn|ugnen|grilla|baka)\b", text, re.IGNORECASE) and "°C" not in text:
        rep.tip("receptet nämner ugn men innehåller ingen temperatur i °C (Regel 5).")


# --------------------------------------------------------------------------

def validate(path: Path, fix: bool) -> Report:
    rep = Report(path=path)
    text = path.read_text(encoding="utf-8")

    # Normalisera alltid i minnet sa att analysen ser ett enhetligt format.
    # Med --fix skrivs resultatet ocksa till filen; utan --fix ar avvikelserna fel.
    text, deviations = normalize(text)
    if deviations:
        if fix:
            path.write_text(text, encoding="utf-8")
            rep.fixes = deviations
        else:
            for dev in deviations:
                rep.error(f"{dev} (Regel 3 — kör hooken eller `--fix` för att normalisera)")

    lines = text.split("\n")
    check_structure(path, lines, rep)
    ingredients = parse_ingredients(lines, rep)
    if not ingredients:
        rep.error("hittar inga ingrediensrader under '## Ingredienser' (Regel 3).")
    check_amounts(ingredients, parse_steps(lines), rep)
    check_totals_table(lines, ingredients, rep)
    check_step_shape(lines, rep)
    check_prose(lines, rep)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Validera receptfiler mot receptstandarden.")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--fix", action="store_true", help="normalisera mekaniska fel i filen")
    ap.add_argument("--quiet", action="store_true", help="skriv bara ut filer med fel")
    args = ap.parse_args()

    failed = False
    for path in args.files:
        if not path.is_file():
            print(f"{path}: filen finns inte", file=sys.stderr)
            return 2
        rep = validate(path, args.fix)
        if rep.errors:
            failed = True
        if rep.errors or rep.fixes or (rep.tips and not args.quiet):
            print(rep.render())
    if failed:
        print(
            "\nRätta alla FEL enligt .claude/rules/recipe-style.md och skriv om filen.",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
