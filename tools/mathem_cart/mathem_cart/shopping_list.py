"""Parse 03-handlingslista.md into Items (spec §5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Item:
    name: str                 # as written, parentheticals removed: "Vispgrädde"
    key: str                  # normalize_key(name): pins key, "vispgrädde"
    amount: float | None      # in `unit`; None when unparseable (always undecided)
    unit: str | None          # "g" "kg" "ml" "cl" "dl" "l" "msk" "tsk" "krm" "st" "förp" "knippe" "burk" "paket"
    category: str             # nearest "## " heading, emoji stripped
    note: str | None = None   # other parentheticals / text after a comma
    verify: bool = False      # "(verifiera)" present
    line_no: int = 0
    raw: str = ""


def normalize_key(name: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", name)
    return re.sub(r"\s+", " ", text).strip().casefold()


UNITS = ("kg", "g", "ml", "cl", "dl", "l", "msk", "tsk", "krm", "st", "förp", "knippe", "burk", "paket",
         "kruka", "flaska", "limpa", "påse", "tub")
# Plural and spelled-out forms seen in real lists, mapped to the canonical unit.
UNIT_ALIASES = {"förpackningar": "förp", "förpackning": "förp", "burkar": "burk", "knippen": "knippe",
                "krukor": "kruka", "flaskor": "flaska", "limpor": "limpa", "påsar": "påse", "tuber": "tub",
                "hela": "st", "hel": "st", "stjälkar": "st", "stjälk": "st"}
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}
# Sections whose entries are listed under "Ej med" in the report (assumed at home or bought elsewhere).
EXCLUDED_SECTIONS = ("skafferi-antaganden", "skafferiantaganden", "specialingredienser", "pantry",
                     "finns hemma", "redan inköpt")
# Sections that are commentary, not shopping (seen in real lists): ignored entirely.
IGNORED_SECTIONS = ("att verifiera", "verifiera", "ungefärlig kostnad", "kostnad", "poolning", "noteringar",
                    "inköpsstrategi", "inkoepsstrategi", "hållbarhet")
# Anywhere in a heading: "## Skafferi — kontrollera hemma", "### Finns hemma — köp inte".
EXCLUDED_KEYWORDS = ("kontrollera hemma", "köp inte", "köps inte", "finns hemma", "antas hemma", "ingår ej")
SKIPPED_SECTIONS = EXCLUDED_SECTIONS  # kept for callers of the old name
NAME_HEADERS = ("vara", "ingrediens", "produkt")
AMOUNT_HEADERS = ("mängd", "antal")
NOTE_HEADERS = ("not", "kommentar", "anteckning")

_NUM = r"\d+(?:[.,]\d+)?"
_FRAC = "[" + "".join(FRACTIONS) + "]"
_ONE = rf"(?:{_NUM}(?:\s*{_FRAC})?|{_FRAC})"
_UNIT_WORDS = sorted((*UNITS, *UNIT_ALIASES), key=len, reverse=True)
# The trailing lookahead stops "g" matching the start of "gurka": the engine
# backtracks to "no unit", which then means pieces ("st"). A unit may end in a
# period ("förp.", "msk.") or be followed by "/" ("1 burk/paket").
_UNIT_ALT = "|".join(_UNIT_WORDS)
_AMOUNT_RE = re.compile(
    rf"^(?:(?:ca|cirka|till)\.?\s+)?(?:(?P<mult>\d+)\s*[x×]\s*)?"
    rf"(?P<amount>{_ONE}(?:\s*[–-]\s*{_ONE})?)\s*"
    rf"(?:(?:liten|litet|lilla|små|stor|stort|stora)\s+(?=(?:{_UNIT_ALT})(?:[\s/,;.]|$)))?"
    rf"(?:(?P<unit>{_UNIT_ALT})\.?)?(?=[\s/,;]|$)",
    re.IGNORECASE,
)
_MINSTA_RE = re.compile(r"^minsta\s+\w+", re.IGNORECASE)   # "minsta påsen" = one package
_NAME_DASH_RE = re.compile(r"\s+[—–]\s+")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s+)?(?P<body>.+?)\s*$")
_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_SUBHEADING_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_ROW_RE = re.compile(r"^\s*\|(?P<cells>.*)\|\s*$")
_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")


@dataclass
class ShoppingList:
    items: list[Item] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def _value(part: str) -> float:
    m = re.match(rf"^\s*({_NUM})?\s*({_FRAC})?\s*$", part)
    total = 0.0
    if m and m.group(1):
        total += float(m.group(1).replace(",", "."))
    if m and m.group(2):
        total += FRACTIONS[m.group(2)]
    return total


def _upper_bound(text: str) -> float:
    """A range "2–3" buys the upper bound."""
    return max(_value(p) for p in re.split(r"[–-]", text))


def _parse_amount(text: str) -> tuple[float | None, str | None, str]:
    """Leading amount and unit of ``text``; returns (amount, unit, the rest)."""
    m = _AMOUNT_RE.match(text)
    if not m:
        minsta = _MINSTA_RE.match(text)
        if minsta:
            return 1.0, "förp", text[minsta.end():]
        return None, None, text
    amount = _upper_bound(m.group("amount")) * (int(m.group("mult")) if m.group("mult") else 1)
    unit = (m.group("unit") or "st").lower()
    return amount, UNIT_ALIASES.get(unit, unit), text[m.end():]


def _clean_heading(title: str) -> str:
    return re.sub(r"^\W+", "", title).strip()


def _strip_markdown(text: str) -> str:
    return re.sub(r"\*+|`", "", text).strip()


def _parentheticals(text: str) -> tuple[str, list[str]]:
    notes = [n.strip() for n in re.findall(r"\(([^)]*)\)", text) if n.strip()]
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", text)).strip(), notes


def _excluded_names(body: str) -> list[str]:
    text, _ = _parentheticals(_strip_markdown(body))
    parts = _NAME_DASH_RE.split(text, maxsplit=1)
    text = parts[0]
    if len(parts) == 2:  # "Laxfilé, fryst — 500 g": the comma qualifies the name
        return [n] if (n := text.split(",")[0].strip(" -–—;.")) else []
    names = (n.strip(" -–—;.") for n in text.split(":")[0].split(","))
    return [n for n in names if n]


def _section_of(title: str) -> str:
    folded = title.casefold()
    if folded.startswith(EXCLUDED_SECTIONS) or any(k in folded for k in EXCLUDED_KEYWORDS):
        return "excluded"
    if folded.startswith(IGNORED_SECTIONS):
        return "ignored"
    return "items"


def _is_verify(note: str) -> bool:
    return note.casefold().startswith("verifiera")


def _item(name: str, amount: float | None, unit: str | None, notes: list[str], category: str,
          line_no: int, raw: str) -> Item | None:
    name = name.strip(" -–—:;.")
    if not name:
        return None
    verify = any(_is_verify(n) for n in notes)
    notes = [n for n in notes if n and n.casefold() != "verifiera"]
    return Item(name=name, key=normalize_key(name), amount=amount, unit=unit, category=category,
                note="; ".join(notes) or None, verify=verify, line_no=line_no, raw=raw.strip())


def parse_line(body: str, category: str, line_no: int = 0, raw: str = "") -> Item | None:
    body = _strip_markdown(body)
    parts = _NAME_DASH_RE.split(body, maxsplit=1)
    if len(parts) == 2 and _parse_amount(_parentheticals(parts[0])[0])[0] is None:
        # Name first: "Cheddar, lagrad — 400 g (Fredagstacos)"
        name_text, notes = _parentheticals(parts[0])
        name, _, tail = name_text.partition(",")
        if tail.strip():
            notes.append(tail.strip())
        amount_text, amount_notes = _parentheticals(parts[1])
        amount, unit, rest = _parse_amount(amount_text)
        notes += amount_notes
        if rest := rest.strip(" /,;-–—"):
            notes.append(rest)
        return _item(name, amount, unit, notes, category, line_no, raw)
    text, notes = _parentheticals(body)
    amount, unit, text = _parse_amount(text)
    name, _, tail = text.partition(",")
    if tail.strip():
        notes.append(tail.strip())
    return _item(name, amount, unit, notes, category, line_no, raw)


def parse_table_row(name_cell: str, amount_cell: str, note_cells: list[str], category: str,
                    line_no: int = 0, raw: str = "") -> Item | None:
    """One row of a "| Vara | Mängd | … | Not |" table."""
    name, notes = _parentheticals(_strip_markdown(name_cell))
    name, *alternatives = [part.strip() for part in name.split("/")]
    notes += [a for a in alternatives if a]
    amount_text, amount_notes = _parentheticals(_strip_markdown(amount_cell))
    notes += amount_notes
    amount, unit, rest = _parse_amount(amount_text)
    rest = rest.strip(" /,-–—")
    if rest:
        notes.append(rest)
    for cell in note_cells:
        text = re.sub(r"\s+", " ", re.sub(r"[()]", "", _strip_markdown(cell))).strip()
        if text:
            notes.append(text)
    return _item(name, amount, unit, notes, category, line_no, raw)


def _header_index(cells: list[str], names: tuple[str, ...]) -> list[int]:
    return [i for i, c in enumerate(cells) if _strip_markdown(c).casefold().startswith(names)]


def parse_shopping_list(text: str) -> ShoppingList:
    result = ShoppingList()
    category: str | None = None
    section = base_section = "items"   # "items" | "excluded" | "ignored"
    table: dict | None = None     # column indices of the current table, {} = not a shopping table
    special: set[int] = set()     # indices in result.excluded that came from a Specialingredienser section
    for line_no, line in enumerate(text.splitlines(), start=1):
        heading = _HEADING_RE.match(line)
        if heading:
            category = _clean_heading(heading.group("title"))
            section = base_section = _section_of(category)
            table = None
            continue
        sub = _SUBHEADING_RE.match(line)
        if sub:  # "### Finns hemma — köp inte" inside a category; lasts until the next heading
            kind = _section_of(_clean_heading(sub.group("title")))
            section = kind if kind != "items" else base_section
            table = None
            continue
        row = _ROW_RE.match(line)
        if row:
            cells = [c.strip() for c in row.group("cells").split("|")]
            if table is None:  # header row
                names, amounts = _header_index(cells, NAME_HEADERS), _header_index(cells, AMOUNT_HEADERS)
                table = {}
                if names and (amounts or section == "excluded"):
                    table = {"name": names[0], "amount": amounts[0] if amounts else None,
                             "notes": _header_index(cells, NOTE_HEADERS)}
                continue
            if not table or category is None or section == "ignored" \
                    or all(_SEPARATOR_CELL.match(c) for c in cells if c):
                continue
            get = lambda i: cells[i] if i is not None and i < len(cells) else ""  # noqa: E731
            if section == "excluded":
                _exclude(result, special, _excluded_names(get(table["name"])), category)
                continue
            item = parse_table_row(get(table["name"]), get(table["amount"]),
                                   [get(i) for i in table["notes"]], category, line_no, line)
            if item:
                result.items.append(item)
            continue
        table = None
        bullet = _BULLET_RE.match(line)
        if not bullet or category is None or section == "ignored":
            continue
        if section == "excluded":
            _exclude(result, special, _excluded_names(bullet.group("body")), category)
            continue
        item = parse_line(bullet.group("body"), category, line_no, line)
        if item:
            result.items.append(item)
    # A special-ingredient note about an item that is on the list is not "Ej med".
    keys = [i.key for i in result.items]
    result.excluded = [n for i, n in enumerate(result.excluded) if i not in special or not _listed(n, keys)]
    return result


def _exclude(result: ShoppingList, special: set[int], names: list[str], category: str | None) -> None:
    for name in names:
        if (category or "").casefold().startswith("specialingredienser"):
            special.add(len(result.excluded))
        result.excluded.append(name)


def _listed(name: str, keys: list[str]) -> bool:
    """"Förkokta kastanjer" ~ "kastanjer", "Perilla" ~ "perillablad": a shared word or word prefix."""
    words = [w for w in re.findall(r"\w+", normalize_key(name)) if len(w) >= 4]
    return any(k.startswith(w) or w.startswith(k)
               for key in keys for k in re.findall(r"\w+", key) if len(k) >= 4 for w in words)


def load_shopping_list(path: Path) -> ShoppingList:
    if not path.is_file():
        raise FileNotFoundError(f"Hittar inte handlingslistan: {path}")
    return parse_shopping_list(path.read_text(encoding="utf-8"))
