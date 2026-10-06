"""Pure: choose product and package count for one item (spec §7)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from typing import Callable, Sequence

from .packaging import Deal, Package, Pricing
from .units import Amount

EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Offer:
    product_id: int
    name: str
    price: float
    unit_price: float | None
    package: Package
    pricing: Pricing
    unit_price_unit: str | None = None   # what `unit_price` is per: "kg", "l", "st"


@dataclass(frozen=True, slots=True)
class Option:
    offer: Offer
    count: int
    cost: float
    overshoot: float
    flags: tuple[str, ...]
    unit_cost: float = math.inf   # effective jämförpris: cost per unit bought (see `_unit_cost`)
    measured: bool = False        # overshoot is a real amount (not förp, not the spoon fallback)


@dataclass(frozen=True, slots=True)
class StockUp:
    """Stock-up mode: a bigger pack may cost this much more than the cheapest option (whichever is smaller).

    `max_extra_share` None: only the kronor cap applies (basvaror: a 5 kg sack of potatoes
    costs several times the 1 kg bag, so a share of the cheapest never lets it in).
    `min_saving`: the bigger pack's jämförpris must be at least this share below the
    cheapest option's, or the cheapest stays; without a known jämförpris for the cheapest
    there is no saving to show, so it stays too. `max_amount`: never buy more than this in
    total (in the package's dimension). `max_multiple`: never buy more than this many times
    the need, so 1 dl ris doesn't bring home a 10 kg sack. An option whose amount can't be
    measured against a set limit is out. The cheapest option is always allowed.
    """

    max_extra_share: float | None = 0.5
    max_extra_kr: float = 100.0
    min_saving: float = 0.0
    max_amount: Amount | None = None
    max_multiple: float | None = None

    def allowance(self, cheapest: float) -> float:
        if self.max_extra_share is None:
            return self.max_extra_kr
        return min(cheapest * self.max_extra_share, self.max_extra_kr)

    def fits(self, option: "Option") -> bool:
        """Within `max_amount` and `max_multiple`."""
        if self.max_multiple is not None and (not option.measured or 1 + option.overshoot > self.max_multiple + EPS):
            return False
        if self.max_amount is None:
            return True
        size = option.offer.package.size
        if size is None or size.dim != self.max_amount.dim:
            return False
        return option.count * size.value <= self.max_amount.value + EPS


@dataclass(frozen=True, slots=True)
class Choice:
    option: Option | None
    reason: str | None
    options: tuple[Option, ...]


# (need, package dimension, offer) -> need in that dimension, or None if no path.
Converter = Callable[[Amount, str, Offer], Amount | None]


def same_dim(amount: Amount, dim: str, offer: Offer | None = None) -> Amount | None:
    return amount if amount.dim == dim else None


def cost_for(count: int, price: float, deals: Sequence[Deal] = (), discount_limit: int | None = None,
             undiscounted_price: float | None = None) -> float:
    """Total price for `count` units.

    `price` is gross_price, which already includes any -P% discount (V8). When the
    discount has a per-customer limit, units beyond it cost the undiscounted price.
    Multibuy deals ("N för X kr") are applied in whole groups, only when cheaper, to
    the units within the limit.
    """
    if discount_limit is not None and undiscounted_price is not None and count > discount_limit:
        return round(_with_deals(discount_limit, price, deals)
                     + (count - discount_limit) * undiscounted_price, 2)
    return round(_with_deals(count, price, deals), 2)


def _with_deals(count: int, price: float, deals: Sequence[Deal]) -> float:
    best = count * price
    for deal in deals:
        if deal.count > 0:
            groups, rest = divmod(count, deal.count)
            best = min(best, groups * deal.price + rest * price)
    return best


def _sort_key(o: Option) -> tuple[float, float, float]:
    unit = o.offer.unit_price if o.offer.unit_price is not None else math.inf
    return (o.cost, unit, o.overshoot)


def _stock_key(o: Option) -> tuple[float, float, float]:
    return (o.unit_cost, o.cost, o.overshoot)


def _unit_key(offer: Offer) -> str:
    return (offer.unit_price_unit or "").casefold()


def _listed_unit(offers: Sequence[Offer]) -> str | None:
    """The jämförpris unit a strict majority of the priced offers share, else None.

    kr/st against kr/kg says nothing, so offers in another unit are never compared on
    jämförpris; without a majority no offer is, and the cheapest total wins.
    """
    counts = Counter(_unit_key(o) for o in offers if o.unit_price is not None)
    ranked = counts.most_common(2)
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def _unit_cost(need: Amount, offer: Offer, cost: float, overshoot: float | None,
               listed_unit: str | None) -> float:
    """Kr per unit actually bought, so multibuy deals and discount limits count.

    Measured in the need's own unit, which every option of an item shares. A need in
    packages (`förp`) has no common amount, so Mathem's listed jämförpris stands in, but
    only in `listed_unit` (see `_listed_unit`); an option bought as one package without a
    size (spoon fallback) has no known amount.
    """
    if need.dim == "förp":
        if offer.unit_price is None or listed_unit is None or _unit_key(offer) != listed_unit:
            return math.inf
        return offer.unit_price
    if overshoot is None:
        return math.inf
    return cost / (need.value * (1 + overshoot))


def choose(need: Amount, offers: Sequence[Offer], *, max_overshoot: float | None,
           convert: Converter = same_dim, spoon_measure: bool = False,
           stock_up: StockUp | None = None) -> Choice:
    """Cheapest option within the overshoot cap (None = frysbar, no cap).

    Tie → lower jämförpris → smaller overshoot. If every option exceeds the cap, the
    smallest overshoot wins and is flagged `överköp`. No usable offer → reason.
    `spoon_measure`: the need came from msk/tsk/krm, so an offer the need can't be
    converted to (a jar sold by weight) counts as one package (spec §7).

    `stock_up` (storpack, basvaror): items worth having at home. No overshoot cap; among
    the options costing at most `stock_up.allowance(cheapest)` more than the cheapest and
    within `stock_up`'s amount limits, the lowest effective jämförpris wins (tie → lower cost →
    smaller overshoot), unless it saves less than `stock_up.min_saving` per unit. Flagged
    `storpack` when it isn't the cheapest.
    """
    options: list[Option] = []
    blocked_by_limit = False
    listed_unit = _listed_unit([o for o in offers if o.price is not None]) if need.dim == "förp" else None
    for offer in offers:
        if offer.price is None:
            continue
        size = offer.package.size
        if need.dim == "förp":
            # V5: a number of packages whatever the size, so an unsized offer is fine.
            count, overshoot = max(1, math.ceil(need.value - EPS)), 0.0
            measured = overshoot
        else:
            sized = size is not None and size.value > 0
            n = convert(need, size.dim, offer) if sized else None
            if n is not None and n.value > 0 and sized:
                count = max(1, math.ceil(n.value / size.value - EPS))
                overshoot = (count * size.value - n.value) / n.value
                measured = overshoot
            elif spoon_measure:
                count, overshoot, measured = 1, 0.0, None
            else:
                continue
        if offer.package.max_count is not None and count > offer.package.max_count:
            blocked_by_limit = True
            continue
        flags = list(offer.package.flags)
        if offer.package.approximate:
            flags.append("ungefärlig")
        cost = cost_for(count, offer.price, offer.pricing.deals, offer.pricing.discount_limit,
                        offer.pricing.undiscounted_price)
        options.append(Option(offer, count, cost, round(overshoot, 4), tuple(flags),
                              _unit_cost(need, offer, cost, measured, listed_unit),
                              measured is not None and need.dim != "förp"))
    if not options:
        reason = "max antal per kund räcker inte" if blocked_by_limit else "ingen förpackning går att räkna"
        return Choice(None, reason, ())
    ranked = tuple(sorted(options, key=_sort_key))
    if stock_up is not None:
        cheapest = ranked[0]
        ceiling = cheapest.cost + stock_up.allowance(cheapest.cost) + EPS
        best = min((o for o in ranked if o.cost <= ceiling
                    and (o is cheapest or stock_up.fits(o))), key=_stock_key)
        if stock_up.min_saving > 0 and (not math.isfinite(cheapest.unit_cost)
                                        or best.unit_cost > cheapest.unit_cost * (1 - stock_up.min_saving) + EPS):
            best = cheapest
        if best is not cheapest and best.cost > cheapest.cost + EPS:
            best = replace(best, flags=best.flags + ("storpack",))
        return Choice(best, None, ranked)
    within = [o for o in ranked if max_overshoot is None or o.overshoot <= max_overshoot + EPS]
    if within:
        return Choice(within[0], None, ranked)
    best = min(ranked, key=lambda o: (o.overshoot, *_sort_key(o)))
    return Choice(replace(best, flags=best.flags + ("överköp",)), None, ranked)
