"""Validate one matcher answer file against its part of the candidate file (matching spec §6.2, §7).

Every answer is untrusted input. A file that breaks the schema makes all its items
undecided; a bad item makes only that item undecided. An id is kept only when it is among
that item's own candidates, so no answer can add a product. Pure apart from reading the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from .candidates import REVIEW

DECISIONS = ("vald", "osäker", "ingen_passar")
MAX_REASON = 160
UNANSWERED = "besvarades inte"
DUPLICATE = "dubbelt svar"
BAD_TERM = "ogiltig sökterm"


@dataclass(frozen=True)
class Verdict:
    vara_id: str
    decision: str                 # "vald" | "osäker" | "ingen_passar"
    approved: tuple[int, ...]
    reason: str
    new_term: str | None = None


@dataclass
class PartResult:
    part: int | str
    status: str                   # "ok" | "saknas" | "ogiltig"
    error: str | None = None
    verdicts: dict[str, Verdict] = field(default_factory=dict)
    unresolved: dict[str, str] = field(default_factory=dict)   # vara_id -> undecided reason
    warnings: list[str] = field(default_factory=list)


class _Invalid(ValueError):
    pass


def label(part: int | str) -> str:
    return REVIEW if part == REVIEW else f"batch {part}"


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_int(value: Any) -> bool:
    return type(value) is int      # bool is an int subclass; True is not a product id


def _unfence(text: str) -> tuple[str, bool]:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```") and "\n" in stripped:
        return stripped[stripped.index("\n") + 1:-3].strip(), True
    return stripped, False


class _Entry(NamedTuple):
    vara_id: str
    decision: str
    ids: list[int]
    reason: str
    term: str | None


def _entry(index: int, raw: Any) -> _Entry:
    where = f"svar[{index}]"
    if not isinstance(raw, dict):
        raise _Invalid(f"{where} är inte ett objekt")
    vid = raw.get("vara_id")
    if not isinstance(vid, str) or not vid:
        raise _Invalid(f"{where}.vara_id måste vara en sträng")
    decision = raw.get("beslut")
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise _Invalid(f"{where}.beslut måste vara vald, osäker eller ingen_passar, inte {decision!r}")
    ids = raw.get("godkända")
    if not isinstance(ids, list) or not all(_is_int(x) for x in ids):
        raise _Invalid(f"{where}.godkända måste vara en lista med produkt-id (heltal)")
    reason = raw.get("motivering")
    if not isinstance(reason, str):
        raise _Invalid(f"{where}.motivering måste vara en sträng")
    term = raw.get("ny_sökterm")
    if term is not None and not isinstance(term, str):
        raise _Invalid(f"{where}.ny_sökterm måste vara en sträng eller null")
    return _Entry(vid, decision, list(dict.fromkeys(ids)), reason, (term.strip() or None) if term else None)


def validate_answer(data: Any, part: Mapping[str, Any], *, kandidat_id: str, round_no: int,
                    batch: int | str) -> PartResult:
    name = label(batch)
    if not isinstance(data, dict):
        return PartResult(batch, "ogiltig", error="svaret är inte ett JSON-objekt")
    if data.get("kandidat_id") != kandidat_id or not _is_int(data.get("omgång")) or data["omgång"] != round_no:
        return PartResult(batch, "saknas", warnings=[
            f"{name}: svaret hör till en annan kandidatfil (kandidat_id eller omgång) och ignoreras"])
    try:
        got = data.get("batch")
        if got != batch or (batch != REVIEW and not _is_int(got)):
            raise _Invalid(f"batch är {got!r}, väntade {batch!r}")
        entries = data.get("svar")
        if not isinstance(entries, list):
            raise _Invalid("svar måste vara en lista")
        parsed = [_entry(i, raw) for i, raw in enumerate(entries)]
    except _Invalid as err:
        return PartResult(batch, "ogiltig", error=str(err))

    result = PartResult(batch, "ok")
    expected = {v["vara_id"]: v for v in part["varor"]}
    by_item: dict[str, list[tuple[str, str, list[int], str, str | None]]] = {}
    for entry in parsed:
        if entry.vara_id not in expected:
            result.warnings.append(f"{name}: svar för okänd vara {entry.vara_id} ignoreras")
            continue
        by_item.setdefault(entry.vara_id, []).append(entry)

    for vid, item in expected.items():
        found = by_item.get(vid, [])
        if not found:
            result.unresolved[vid] = UNANSWERED
            continue
        if len(found) > 1:
            result.unresolved[vid] = DUPLICATE
            continue
        _, decision, ids, reason, term = found[0]
        where = f"{name}: {vid} {item.get('vara', '')}".rstrip()
        allowed = {c["produkt_id"] for c in item.get("kandidater", [])}
        outside = [i for i in ids if i not in allowed]
        if outside:
            result.warnings.append(f"{where}: id {', '.join(map(str, outside))} finns inte bland varans "
                                   "kandidater och ignoreras")
        approved = () if decision == "ingen_passar" else tuple(i for i in ids if i in allowed)
        if term is not None:
            searched = {_norm(item.get("sökterm", "")), _norm(item.get("vara", ""))}
            if batch == REVIEW or round_no != 1 or decision != "ingen_passar" or _norm(term) in searched:
                result.unresolved[vid] = BAD_TERM
                result.warnings.append(f"{where}: ny_sökterm “{term}” ignoreras")
                continue
        if decision == "vald" and not approved:
            decision = "osäker"
        reason = reason.strip()
        if len(reason) > MAX_REASON:
            result.warnings.append(f"{where}: motiveringen kortades till {MAX_REASON} tecken")
            reason = reason[:MAX_REASON]
        result.verdicts[vid] = Verdict(vid, decision, approved, reason, term)
    return result


def load_answer(path: Path, part: Mapping[str, Any], *, kandidat_id: str, round_no: int,
                batch: int | str) -> PartResult:
    if not Path(path).is_file():
        return PartResult(batch, "saknas")
    try:
        text, fenced = _unfence(Path(path).read_text(encoding="utf-8-sig"))
        data = json.loads(text)
    except (OSError, ValueError) as err:          # JSONDecodeError and UnicodeDecodeError are ValueErrors
        return PartResult(batch, "ogiltig", error=f"ogiltig JSON: {err}")
    result = validate_answer(data, part, kandidat_id=kandidat_id, round_no=round_no, batch=batch)
    if fenced:
        result.warnings.insert(0, f"{label(batch)}: svaret låg i ett kodblock (```), läses ändå")
    return result
