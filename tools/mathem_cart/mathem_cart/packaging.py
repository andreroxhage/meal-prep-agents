"""Package size, per-customer limit and deals from a Product (spec §7)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .mathem.models import Product, parse_price
from .units import Amount, to_base


@dataclass(frozen=True, slots=True)
class Package:
    size: Amount | None
    max_count: int | None = None
    approximate: bool = False
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Deal:
    count: int      # buy this many …
    price: float    # … for this total (kr)
    title: str


@dataclass(frozen=True, slots=True)
class Pricing:
    deals: tuple[Deal, ...] = ()
    informational: tuple[str, ...] = ()        # shown in report, not applied
    discount_limit: int | None = None          # discount.maximum_quantity
    undiscounted_price: float | None = None    # discount.undiscounted_gross_price


_MAX_RE = re.compile(r"^\s*max\s+(\d+)\s+per\s+kund\s*,?\s*", re.IGNORECASE)
_SIZE_RE = re.compile(
    r"^\s*(?P<approx>ca\.?\s+)?(?:(?P<mult>\d+)\s*[x×]\s*)?(?P<num>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|ml|cl|dl|l|st)(?!\w)", re.IGNORECASE)
_PACK_RE = re.compile(r"^\s*(?P<n>\d+)\s*-?\s*pack(?!\w)", re.IGNORECASE)
_MULTI_RE = re.compile(r"^\s*(\d+)\s+för\s+(\d+(?:[.,]\d+)?)\s*(kr)?\s*$", re.IGNORECASE)
_PERCENT_RE = re.compile(r"^\s*-\s*\d+(?:[.,]\d+)?\s*%\s*$")
_FALLBACK_DIM = {"kg": ("g", 1000.0), "l": ("ml", 1000.0), "st": ("st", 1.0)}
TOLERANCE = 0.05


def _parse_size(text: str) -> tuple[Amount | None, bool]:
    m = _SIZE_RE.match(text)
    if m:
        value = float(m.group("num").replace(",", ".")) * (int(m.group("mult")) if m.group("mult") else 1)
        return to_base(value, m.group("unit")), bool(m.group("approx"))
    m = _PACK_RE.match(text)
    if m:
        return Amount(float(m.group("n")), "st"), False
    return None, False


def _from_unit_price(p: Product) -> Amount | None:
    """Package size implied by gross_price / gross_unit_price (jämförpris)."""
    unit = (p.unit_price_unit or "").lower()
    if unit not in _FALLBACK_DIM or not p.gross_price or not p.gross_unit_price:
        return None
    dim, factor = _FALLBACK_DIM[unit]
    return Amount(round(p.gross_price / p.gross_unit_price * factor, 1), dim)


def parse_package(p: Product) -> Package:
    """Size in base units from ``name_extra``, cross-checked against the jämförpris."""
    text = p.name_extra or ""
    max_count = None
    m = _MAX_RE.match(text)
    if m:
        max_count = int(m.group(1))
        text = text[m.end():]
    size, approximate = _parse_size(text)
    if size is None and "," in text:
        # "Sverige, 3000 g" / "2 portioner, 500 g": the size is the last segment.
        size, approximate = _parse_size(text.rsplit(",", 1)[1])
    fallback = _from_unit_price(p)
    if size is None or size.value <= 0:
        if fallback is None or fallback.value <= 0:
            return Package(None, max_count)
        return Package(fallback, max_count, False, ("storlek_från_jämförpris",))
    flags: tuple[str, ...] = ()
    # A jämförpris in another dimension (Oatly Visp: 250 ml priced per kg) says nothing.
    if fallback and fallback.dim == size.dim and abs(fallback.value - size.value) / size.value > TOLERANCE:
        flags = ("storlek_osäker",)
    return Package(size, max_count, approximate, flags)


def parse_pricing(p: Product) -> Pricing:
    """Multibuy deals to apply; everything else is informational (V8: -P% is already in the price)."""
    deals: list[Deal] = []
    info: list[str] = []
    for title in p.promotions:
        m = _MULTI_RE.match(title)
        if m:
            count, other = int(m.group(1)), float(m.group(2).replace(",", "."))
            if count <= 0:
                info.append(title)
            elif m.group(3) or other >= count:
                deals.append(Deal(count, other, title))
            elif p.gross_price:
                deals.append(Deal(count, round(other * p.gross_price, 2), title))
            else:
                info.append(title)
        elif _PERCENT_RE.match(title):
            # Verified 2026-09-24: gross_price already includes the percentage.
            info.append(f"{title} (ingår i priset)")
        else:
            info.append(title)
    d = p.discount or {}
    limit = d.get("maximum_quantity")
    return Pricing(tuple(deals), tuple(info),
                   int(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) else None,
                   parse_price(d.get("undiscounted_gross_price")))
