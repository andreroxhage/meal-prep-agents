"""Plan and apply-result data model, plus the `06-mathem-plan.json` format (spec §9).

Python identifiers are English; the JSON keys are the Swedish keys from the spec.
This module depends on nothing else in the package, so `report.py` can render a plan
without importing the planner or the client (plan deviation V6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Undecided reasons that more than one module sets.
AMOUNT_MISSING = "mängd saknas"
UNKNOWN_UNIT = "okänd enhet"
NO_CANDIDATES = "inga kandidater"


def _num(x: float | int | None) -> float | int | None:
    """Keep whole numbers as ints in JSON (300.0 -> 300)."""
    if x is None:
        return None
    return int(x) if float(x).is_integer() else x


@dataclass
class Need:
    """How much the shopping list asks for, in base units (g/ml/st/förp); None/None if unknown."""

    amount: float | None
    unit: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"mängd": _num(self.amount), "enhet": self.unit}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Need:
        return cls(d.get("mängd"), d.get("enhet"))


@dataclass
class PlanLine:
    """One decided line: an item from the list, the product and how many packages."""

    item: str
    need: Need
    category: str
    product_id: int
    name: str
    package: str
    count: int
    cost_kr: float
    unit_price: str | None
    deal: str | None
    overshoot: float
    decision: str  # "pin" | "fast" | "haiku" | "sonnet"
    flags: list[str] = field(default_factory=list)
    reason: str | None = None  # the model's "motivering"; None for pins and fixed picks

    def to_dict(self) -> dict[str, Any]:
        return {
            "vara": self.item,
            "behov": self.need.to_dict(),
            "kategori": self.category,
            "produkt_id": self.product_id,
            "namn": self.name,
            "förpackning": self.package,
            "antal": self.count,
            "kostnad_kr": self.cost_kr,
            "jämförpris": self.unit_price,
            "kampanj": self.deal,
            "överköp": self.overshoot,
            "beslut": self.decision,
            "flaggor": list(self.flags),
            "motivering": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanLine:
        return cls(
            item=d["vara"],
            need=Need.from_dict(d["behov"]),
            category=d["kategori"],
            product_id=int(d["produkt_id"]),
            name=d["namn"],
            package=d["förpackning"],
            count=int(d["antal"]),
            cost_kr=float(d["kostnad_kr"]),
            unit_price=d.get("jämförpris"),
            deal=d.get("kampanj"),
            overshoot=float(d["överköp"]),
            decision=d["beslut"],
            flags=list(d.get("flaggor", [])),
            reason=d.get("motivering"),
        )


@dataclass
class Candidate:
    """A product offered to the user for an undecided item."""

    product_id: int
    name: str
    package: str
    price: float | None
    unit_price: str | None
    deal: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "produkt_id": self.product_id,
            "namn": self.name,
            "förpackning": self.package,
            "pris": self.price,
            "jämförpris": self.unit_price,
            "kampanj": self.deal,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Candidate:
        price = d.get("pris")   # an old "p" (model score) is ignored
        return cls(
            product_id=int(d["produkt_id"]),
            name=d["namn"],
            package=d["förpackning"],
            price=None if price is None else float(price),
            unit_price=d.get("jämförpris"),
            deal=d.get("kampanj"),
        )


@dataclass
class Undecided:
    """An item the planner could not decide on its own."""

    item: str
    need: Need
    category: str
    reason: str
    candidates: list[Candidate] = field(default_factory=list)
    note: str | None = None  # the model's "motivering" when it was unsure

    def to_dict(self) -> dict[str, Any]:
        return {
            "vara": self.item,
            "behov": self.need.to_dict(),
            "kategori": self.category,
            "orsak": self.reason,
            "motivering": self.note,
            "kandidater": [c.to_dict() for c in self.candidates],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Undecided:
        return cls(
            item=d["vara"],
            need=Need.from_dict(d["behov"]),
            category=d.get("kategori", ""),
            reason=d["orsak"],
            candidates=[Candidate.from_dict(c) for c in d.get("kandidater", [])],
            note=d.get("motivering"),
        )


@dataclass
class Plan:
    """The whole reviewed plan, written to `06-mathem-plan.json`."""

    week: str
    created: datetime
    lines: list[PlanLine]
    undecided: list[Undecided]
    skipped: list[str]
    excluded: list[str]
    warnings: list[str]
    total_kr: float  # round(sum(line.cost_kr), 2); set by the planner

    def to_dict(self) -> dict[str, Any]:
        return {
            "vecka": self.week,
            "skapad": self.created.isoformat(),
            "rader": [line.to_dict() for line in self.lines],
            "undecided": [u.to_dict() for u in self.undecided],
            "hoppade": list(self.skipped),
            "ej_med": list(self.excluded),
            "varningar": list(self.warnings),
            "total_kr": self.total_kr,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Plan:
        created = datetime.fromisoformat(d["skapad"])
        if created.tzinfo is None:
            raise ValueError("skapad saknar tidszon")
        return cls(
            week=d["vecka"],
            created=created,   # an old "läge" is ignored
            lines=[PlanLine.from_dict(x) for x in d.get("rader", [])],
            undecided=[Undecided.from_dict(x) for x in d.get("undecided", [])],
            skipped=list(d.get("hoppade", [])),
            excluded=list(d.get("ej_med", [])),
            warnings=list(d.get("varningar", [])),
            total_kr=float(d["total_kr"]),
        )

    def write(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def read(cls, path: Path) -> Plan:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class ApplyResult:
    """What `apply` did: planned counts vs. counts read back from the cart."""

    applied_at: datetime
    expected: dict[int, int]  # product_id -> planned count (summed)
    actual: dict[int, int]  # product_id -> count in cart after apply
    differences: list[str]  # Swedish, one per problem
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.differences and self.error is None
