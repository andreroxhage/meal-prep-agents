"""The candidate file `06-mathem-kandidater.json` that the matcher agents read (matching spec §5).

A candidate carries its id, name, package and labels, nothing else: the model judges the
product, code judges the cost (M5). Each round's file is also kept under
`.mathem-matchning/omgang-N/` so `decide` can re-validate earlier answers (deviation K5), and
each batch (and the review part) is also written as a small file of its own there: the whole
file is too large for one Read, so every agent reads only its part (deviation K17).
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .mathem.models import Product
from .shopping_list import Item

BATCH_SIZE = 12
SEARCH_ORDER_CANDIDATES = 15       # the first ones, in Mathem's search order
EXTRA_UNIT_PRICE_CANDIDATES = 5    # then the planner's picks by jämförpris (planner.agent_order)
MAX_AGENT_CANDIDATES = SEARCH_ORDER_CANDIDATES + EXTRA_UNIT_PRICE_CANDIDATES   # per item in the candidate file
CANDIDATE_FILE = "06-mathem-kandidater.json"
MATCH_DIR = ".mathem-matchning"
ROUND_COPY = "kandidater.json"
REVIEW = "granskning"
HASHED_KEYS = ("vecka", "omgång", "batcher", "granskning")
FROZEN_KEY = "svar_omgång_1"     # round 2 only: digest of the round-1 answers it was built from (K16)
PART_SUFFIX = "-kandidater.json"


class CandidateFileError(ValueError):
    """The candidate file is missing, unreadable, or changed after it was written."""


@dataclass(frozen=True)
class Pending:
    """An item code could not settle: it goes to a matcher agent with these candidates."""

    item: Item
    vara_id: str
    term: str                                              # the search term that found `products`
    products: list[Product] = field(default_factory=list)  # after the rules, in planner.agent_order


@dataclass(frozen=True)
class Review:
    """A round-1 `osäker` item for the reviewer."""

    pending: Pending
    approved: list[int]
    reason: str


def vara_id(position: int) -> str:
    return f"v{position:02d}"


def _number(value: float) -> str:
    return f"{float(value):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def behov_text(item: Item) -> str:
    if item.amount is None:
        return "okänt"
    number = _number(item.amount)
    return f"{number} {item.unit}" if item.unit else number


def round_dir(round_no: int) -> str:
    """The round's folder, relative to the week folder."""
    return f"{MATCH_DIR}/omgang-{round_no}"


def _part_file(round_no: int, part: int | str, suffix: str) -> str:
    stem = REVIEW if part == REVIEW else f"batch-{int(part):02d}"
    return f"{round_dir(round_no)}/{stem}{suffix}"


def answer_path(round_no: int, part: int | str) -> str:
    return _part_file(round_no, part, ".json")


def part_path(round_no: int, part: int | str) -> str:
    """Where one part of the candidate file is written on its own, for the agent that judges it."""
    return _part_file(round_no, part, PART_SUFFIX)


def parts_of(file: Mapping[str, Any]) -> list[tuple[int | str, Mapping[str, Any]]]:
    parts: list[tuple[int | str, Mapping[str, Any]]] = [(b["batch"], b) for b in file["batcher"]]
    if file.get("granskning"):
        parts.append((REVIEW, file["granskning"]))
    return parts


def _product(p: Product) -> dict[str, Any]:
    return {"produkt_id": p.id, "namn": p.full_name, "förpackning": p.name_extra or "",
            "märkning": list(p.classifiers)}


def _item(pending: Pending, cap: int) -> dict[str, Any]:
    item = pending.item
    return {"vara_id": pending.vara_id, "vara": item.name, "behov": behov_text(item), "kategori": item.category,
            "anteckning": item.note or "", "sökterm": pending.term,
            "kandidater": [_product(p) for p in pending.products[:cap]]}


def _sizes(count: int, size: int) -> list[int]:
    """Split `count` items into as few batches of at most `size` as possible, evenly."""
    if count == 0:
        return []
    batches = math.ceil(count / size)
    base, extra = divmod(count, batches)
    return [base + (1 if i < extra else 0) for i in range(batches)]


def compute_kandidat_id(file: Mapping[str, Any]) -> str:
    body = {key: file.get(key) for key in HASHED_KEYS}
    if file.get(FROZEN_KEY) is not None:
        body[FROZEN_KEY] = file[FROZEN_KEY]
    return digest(body)


def digest(value: Any) -> str:
    """First 12 hex chars of SHA-256 over canonical JSON (kandidat_id, frozen answers, resend record)."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_candidate_file(week: str, round_no: int, pending: Sequence[Pending], review: Sequence[Review] = (),
                         *, now: datetime, batch_size: int = BATCH_SIZE, cap: int = MAX_AGENT_CANDIDATES,
                         frozen: str | None = None) -> tuple[dict[str, Any], dict[str, int]]:
    everyone = [*pending, *(r.pending for r in review)]
    dropped = {p.vara_id: len(p.products) - cap for p in everyone if len(p.products) > cap}
    batches: list[dict[str, Any]] = []
    start = 0
    for number, size in enumerate(_sizes(len(pending), batch_size), 1):
        chunk = pending[start:start + size]
        start += size
        batches.append({"batch": number, "svarsfil": answer_path(round_no, number),
                        "varor": [_item(p, cap) for p in chunk]})
    part = None
    if review:
        part = {"svarsfil": answer_path(round_no, REVIEW),
                "varor": [{**_item(r.pending, cap),
                           "tidigare": {"beslut": "osäker", "godkända": list(r.approved), "motivering": r.reason}}
                          for r in review]}
    file: dict[str, Any] = {"kandidat_id": "", "vecka": week, "omgång": round_no, "skapad": now.isoformat(),
                            "batcher": batches, "granskning": part}
    if frozen is not None:
        file[FROZEN_KEY] = frozen
    file["kandidat_id"] = compute_kandidat_id(file)
    return file, dropped


def drop_warnings(pending: Sequence[Pending], dropped: Mapping[str, int], cap: int = MAX_AGENT_CANDIDATES) -> list[str]:
    """One line about the items whose candidates were cut to `cap` (spec §5: dropped counts are logged).

    Names the items when there are a few; past that only counts, since most items of a
    real list are capped and one line each drowns the output.
    """
    names = {p.vara_id: p.item.name for p in pending}
    cut = {vid: count for vid, count in dropped.items() if vid in names}
    if not cut:
        return []
    what = (", ".join(f"{names[vid]} +{count}" for vid, count in cut.items()) if len(cut) <= 5
            else f"{sum(cut.values())} bortkapade")
    items = "1 vara" if len(cut) == 1 else f"{len(cut)} varor"
    return [f"{items} hade fler än {cap} kandidater efter reglerna ({what}); agenterna ser de "
            f"{SEARCH_ORDER_CANDIDATES} första i Mathems ordning och upp till {EXTRA_UNIT_PRICE_CANDIDATES} till "
            "med lägst jämförpris"]


def round_copy(week_dir: Path, round_no: int) -> Path:
    return Path(week_dir) / round_dir(round_no) / ROUND_COPY


def _dump(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_round(week_dir: Path, file: Mapping[str, Any]) -> Path:
    text = _dump(file)
    copy = round_copy(week_dir, file["omgång"])
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(text, encoding="utf-8")
    for pid, part in parts_of(file):
        body = {"kandidat_id": file["kandidat_id"], "vecka": file["vecka"], "omgång": file["omgång"], "batch": pid,
                "svarsfil": part["svarsfil"], "varor": part["varor"]}
        (Path(week_dir) / part_path(file["omgång"], pid)).write_text(_dump(body), encoding="utf-8")
    path = Path(week_dir) / CANDIDATE_FILE
    path.write_text(text, encoding="utf-8")
    return path


def read_round(week_dir: Path, round_no: int | None = None) -> dict[str, Any]:
    path = Path(week_dir) / CANDIDATE_FILE if round_no is None else round_copy(week_dir, round_no)
    if not path.is_file():
        raise CandidateFileError(f"hittar inte {path} — kör plan först")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise CandidateFileError(f"{path} är inte giltig JSON ({err}) — kör plan igen") from None
    if (not isinstance(data, dict) or not isinstance(data.get("batcher"), list)
            or type(data.get("omgång")) is not int or data.get("kandidat_id") != compute_kandidat_id(data)):
        raise CandidateFileError(f"{path} har ändrats efter att den skrevs — kör plan igen")
    if round_no is not None and data["omgång"] != round_no:
        raise CandidateFileError(f"{path} hör till omgång {data['omgång']}, inte {round_no} — kör plan igen")
    return data


def clear_matching(week_dir: Path) -> None:
    (Path(week_dir) / CANDIDATE_FILE).unlink(missing_ok=True)
    shutil.rmtree(Path(week_dir) / MATCH_DIR, ignore_errors=True)
