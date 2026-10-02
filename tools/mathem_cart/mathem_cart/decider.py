"""The round state machine behind `decide` (matching spec §4, §7). At most two rounds.

Model output is read only from answer files at paths derived here, under
`<vecka>/.mathem-matchning/`, and checked against that round's candidate file. Every
approved product is re-checked against the current rule-filtered search for the same term,
so an answer — or an edited candidate file — can make an item undecided but never add a
product (deviation K7). This module never sees the user's saved choices: model picks are
not saved (M3). Agents can write any file, so nothing here trusts a file an agent could
reset: round-1 answers are frozen by a digest in the round-2 file, and the resend record
carries a check value (deviation K16).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .answers import REVIEW, PartResult, Verdict, load_answer
from .candidates import (CANDIDATE_FILE, FROZEN_KEY, MATCH_DIR, CandidateFileError, Pending, Review, answer_path,
                         build_candidate_file, digest, drop_warnings, parts_of, read_round, round_copy, round_dir,
                         write_round)
from .mathem.models import Product
from .plan_model import NO_CANDIDATES, PlanLine, Undecided
from .shopping_list import Item

MAX_MATCH_ROUNDS = 2
MISSING = "matchning saknas"
INVALID = "ogiltigt svar"
UNSURE = "osäker"
NONE_FITS = "ingen passar"
RESENT_FILE = "omsändning.json"


class DecideError(Exception):
    """The matching files no longer fit the week; the user has to run `plan` again."""


@dataclass
class DecideDeps:
    week_dir: Path
    week: str
    now: datetime
    pending: list[Pending]
    candidates_for: Callable[[Item, str], list[Product]]
    line_for: Callable[[Item, list[Product], str, str | None], PlanLine | Undecided]
    undecided_for: Callable[[Item, str, Sequence[Product], str | None], Undecided]


@dataclass(frozen=True)
class Resend:
    part: int | str
    path: str
    problem: str


@dataclass
class DecideResult:
    status: str                  # "klar" | "omgång 2" | "skicka om"
    round_no: int
    outcomes: dict[str, PlanLine | Undecided] = field(default_factory=dict)
    resend: list[Resend] = field(default_factory=list)
    candidate_file: Path | None = None
    warnings: list[str] = field(default_factory=list)


class _Round:
    """One round's candidate file and its validated answers."""

    def __init__(self, week_dir: Path, file: Mapping[str, Any], warnings: list[str]):
        self.no: int = file["omgång"]
        self.kandidat_id: str = file["kandidat_id"]
        self.parts = parts_of(file)
        self.results: dict[int | str, PartResult] = {
            pid: load_answer(Path(week_dir) / answer_path(self.no, pid), part, kandidat_id=file["kandidat_id"],
                             round_no=self.no, batch=pid)
            for pid, part in self.parts}
        for result in self.results.values():
            warnings.extend(result.warnings)
        self.part_of = {v["vara_id"]: pid for pid, part in self.parts for v in part["varor"]}
        self.entry = {v["vara_id"]: v for _, part in self.parts for v in part["varor"]}

    def verdict(self, vid: str) -> Verdict | str:
        pid = self.part_of.get(vid)
        if pid is None:
            return MISSING
        result = self.results[pid]
        if result.status == "saknas":
            return MISSING
        if result.status == "ogiltig":
            return INVALID
        return result.unresolved.get(vid) or result.verdicts.get(vid) or MISSING


def _answers_digest(week_dir: Path, rnd: _Round) -> str:
    """What the round's answer files held, byte for byte; a missing file counts as `null`."""
    files = []
    for pid, _ in rnd.parts:
        path = Path(week_dir) / answer_path(rnd.no, pid)
        files.append([str(pid), hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None])
    return digest(files)


def _resent(record: Path, rnd: _Round, warnings: list[str]) -> set[str]:
    """Parts already re-dispatched. A record that doesn't verify counts as all of them (fail closed)."""
    if not record.is_file():
        return set()
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
        parts = data["delar"]
        if (isinstance(parts, list) and all(isinstance(p, str) for p in parts)
                and data["kontroll"] == digest([rnd.kandidat_id, sorted(parts)])):
            return set(parts)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    warnings.append(f"{round_dir(rnd.no)}/{RESENT_FILE} har ändrats — inga fler omsändningar i "
                    f"omgång {rnd.no}")
    return {str(pid) for pid, _ in rnd.parts}


def _resend(week_dir: Path, rnd: _Round, warnings: list[str]) -> list[Resend]:
    """Missing or invalid parts are re-dispatched once (deviation K6)."""
    bad = [(pid, r) for pid, r in rnd.results.items() if r.status != "ok"]
    if not bad:
        return []
    if not any((Path(week_dir) / answer_path(rnd.no, pid)).exists() for pid, _ in rnd.parts):
        return []     # nobody answered: the CLI runs without Claude Code, so nothing to re-dispatch
    record = Path(week_dir) / round_dir(rnd.no) / RESENT_FILE
    done = _resent(record, rnd, warnings)
    todo = [Resend(pid, answer_path(rnd.no, pid), "saknas" if r.status == "saknas" else f"ogiltigt: {r.error}")
            for pid, r in bad if str(pid) not in done]
    if todo:
        parts = sorted(done | {str(t.part) for t in todo})
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"delar": parts, "kontroll": digest([rnd.kandidat_id, parts])},
                                     ensure_ascii=False), encoding="utf-8")
    return todo


def _accept(deps: DecideDeps, item: Item, term: str, verdict: Verdict, source: str) -> PlanLine | Undecided | None:
    approved = set(verdict.approved)
    accepted = [p for p in deps.candidates_for(item, term) if p.id in approved]   # Mathem's search order
    return deps.line_for(item, accepted, source, verdict.reason) if accepted else None


def _second(deps: DecideDeps, rnd: _Round, p: Pending, term: str, source: str,
            review: bool) -> PlanLine | Undecided:
    pid = rnd.part_of.get(p.vara_id)
    if pid is None or (pid == REVIEW) != review:
        return deps.undecided_for(p.item, MISSING, p.products, None)
    verdict = rnd.verdict(p.vara_id)
    if isinstance(verdict, str):
        return deps.undecided_for(p.item, verdict, p.products, None)
    if verdict.decision == "vald":
        line = _accept(deps, p.item, term, verdict, source)
        return line if line is not None else deps.undecided_for(p.item, UNSURE, p.products, verdict.reason)
    reason = UNSURE if verdict.decision == "osäker" else NONE_FITS
    return deps.undecided_for(p.item, reason, p.products, verdict.reason)


def _load(deps: DecideDeps) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
    try:
        current = read_round(deps.week_dir)
        no = current["omgång"]
        if not 1 <= no <= MAX_MATCH_ROUNDS:
            raise DecideError(f"omgång {no} stöds inte — högst {MAX_MATCH_ROUNDS} omgångar; kör plan igen")
        first = read_round(deps.week_dir, 1)
        if read_round(deps.week_dir, no)["kandidat_id"] != current["kandidat_id"]:
            raise DecideError(f"{deps.week_dir / CANDIDATE_FILE} stämmer inte med "
                              f"{MATCH_DIR}/ — kör plan igen")
        for later in range(no + 1, MAX_MATCH_ROUNDS + 1):
            if round_copy(deps.week_dir, later).exists():
                raise DecideError(f"{deps.week_dir / CANDIDATE_FILE} hör till omgång {no}, men "
                                  f"omgång {later} finns redan i {MATCH_DIR}/ — kör plan igen")
    except CandidateFileError as err:
        raise DecideError(str(err)) from None
    return no, first, current if no == 2 else None


def decide(deps: DecideDeps) -> DecideResult:
    no, first_file, second_file = _load(deps)
    warnings: list[str] = []
    try:
        first = _Round(deps.week_dir, first_file, warnings)
        second = _Round(deps.week_dir, second_file, warnings) if second_file else None
    except (KeyError, TypeError) as err:
        raise DecideError(f"kandidatfilen har fel format ({err}) — kör plan igen") from None
    if second_file is not None and second_file.get(FROZEN_KEY) != _answers_digest(deps.week_dir, first):
        raise DecideError("svaren i omgång 1 har ändrats efter att omgång 2 skapades — kör plan igen")
    pending = {p.vara_id: p for p in deps.pending}
    for rnd in (first, second):
        for vid, entry in (rnd.entry.items() if rnd else ()):
            p = pending.get(vid)
            if p is not None and p.item.name != entry.get("vara"):
                raise DecideError(f"handlingslistan har ändrats sedan plan ({vid} är nu “{p.item.name}”, "
                                  f"kandidatfilen säger “{entry.get('vara')}”) — kör plan igen")
    resend = _resend(deps.week_dir, second or first, warnings)
    if resend:
        return DecideResult("skicka om", no, resend=resend, warnings=warnings)

    outcomes: dict[str, PlanLine | Undecided] = {}
    review: list[Review] = []
    research: list[tuple[Pending, str]] = []
    for vid, p in pending.items():
        verdict = first.verdict(vid)
        if isinstance(verdict, str):
            outcomes[vid] = deps.undecided_for(p.item, verdict, p.products, None)
            continue
        if verdict.decision == "vald":
            line = _accept(deps, p.item, p.term, verdict, "haiku")
            if line is not None:
                outcomes[vid] = line
                continue
            warnings.append(f"{p.item.name}: ingen godkänd produkt finns kvar i sökningen — räknas som osäker")
            verdict = Verdict(vid, "osäker", (), verdict.reason)
        if verdict.decision == "osäker":
            review.append(Review(p, list(verdict.approved), verdict.reason))
        elif verdict.new_term:
            research.append((p, verdict.new_term))
        else:
            outcomes[vid] = deps.undecided_for(p.item, NONE_FITS, p.products, verdict.reason)

    batches: list[Pending] = []            # research items with their new term's candidates, in both rounds
    for p, term in research:
        products = deps.candidates_for(p.item, term)
        if products:
            batches.append(Pending(p.item, p.vara_id, term, products))
        else:
            outcomes[p.vara_id] = deps.undecided_for(p.item, NO_CANDIDATES, p.products,
                                                     f"ny sökterm “{term}” gav inga kandidater")

    if second is None:
        if not batches and not review:
            return DecideResult("klar", 1, outcomes=outcomes, warnings=warnings)
        file, dropped = build_candidate_file(deps.week, 2, batches, review, now=deps.now,
                                             frozen=_answers_digest(deps.week_dir, first))
        warnings.extend(drop_warnings(batches, dropped))
        return DecideResult("omgång 2", 2, candidate_file=write_round(deps.week_dir, file), warnings=warnings)

    expected = {r.pending.vara_id for r in review} | {p.vara_id for p, _ in research}
    for r in review:
        outcomes[r.pending.vara_id] = _second(deps, second, r.pending, r.pending.term, "sonnet", review=True)
    for p in batches:
        outcomes[p.vara_id] = _second(deps, second, p, p.term, "haiku", review=False)
    for vid in second.entry:
        if vid not in expected:
            warnings.append(f"omgång 2: {vid} hör inte till omgången och ignoreras")
    return DecideResult("klar", 2, outcomes=outcomes, warnings=warnings)
