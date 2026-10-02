"""Settle what code can settle (matching spec §4). Never calls a model, never logs in.

Per item, in list order: skip list → quantity known? → pin (`fast`, then `godkända`) →
otherwise `Pending`: the item goes to the matcher agents with its candidates (after the
category rules, in Mathem's search order). `line_for` turns an accepted set into a plan
line (quantity maths, spec §7); `decide` calls it with the agents' picks. `ask` handles the
interactive questions and saves the answers as pins (base spec §6 "Asking").
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Collection, Protocol, Sequence

from .candidates import EXTRA_UNIT_PRICE_CANDIDATES, SEARCH_ORDER_CANDIDATES, Pending, vara_id
from .mathem.models import Product
from .packaging import parse_package, parse_pricing
from .pins import Pins
from .plan_model import AMOUNT_MISSING, NO_CANDIDATES, UNKNOWN_UNIT, Candidate, Need, Plan, PlanLine, Undecided
from .quantity import Offer, choose, cost_for
from .rules import Rules, filter_candidates, meets_preference
from .shopping_list import Item, ShoppingList, normalize_key
from .units import SPOON_UNITS, Amount, convert, to_base

MAX_QUESTIONS = 5     # interactive answers per item before giving up
SHOWN_CANDIDATES = 5  # candidates shown for an undecided item
SPICE_CATEGORY = "kryddor & såser"
USER_DECISIONS = ("pin", "fast")


@dataclass(frozen=True)
class Answer:
    kind: str                 # "accept" | "fixed" | "search" | "skip"
    product_id: int | None = None
    term: str | None = None


class Asker(Protocol):
    def ask(self, item: Item, candidates: Sequence[Candidate]) -> Answer: ...


@dataclass
class PlannerDeps:
    search: Callable[[str], list[Product]]
    lookup: Callable[[int], Product | None]
    rules: Rules
    pins: Pins
    warn: Callable[[str], None] = lambda message: None


def agent_order(products: Sequence[Product], head: int = SEARCH_ORDER_CANDIDATES,
                extra: int = EXTRA_UNIT_PRICE_CANDIDATES) -> list[Product]:
    """Mathem's order, except that the `extra` lowest-jämförpris products past the first
    `head` move up right behind them, so they land in the agents' candidate list.

    A big pack with the best price per kg often sits far down the search; without this the
    agents never see it and storpack can't pick it. Only the jämförpris unit most of the
    first `head` use is compared (kr/kg against kr/kg, never against kr/st). The candidate
    file itself stays price-blind; it just keeps the first `head + extra`.
    """
    first, rest = list(products[:head]), list(products[head:])
    units = Counter(p.unit_price_unit for p in first if p.unit_price_unit and p.gross_unit_price is not None)
    if not rest or not units or extra <= 0:
        return first + rest
    unit = units.most_common(1)[0][0]
    priced = [p for p in rest if p.unit_price_unit == unit and p.gross_unit_price is not None]
    picked = sorted(priced, key=lambda p: p.gross_unit_price)[:extra]
    ids = {p.id for p in picked}
    return first + picked + [p for p in rest if p.id not in ids]


def to_offer(p: Product) -> Offer | None:
    """None when the product has no price (it can't be calculated, but it's no crash)."""
    if p.gross_price is None:
        return None
    return Offer(product_id=p.id, name=p.full_name, price=p.gross_price, unit_price=p.gross_unit_price,
                 package=parse_package(p), pricing=parse_pricing(p), unit_price_unit=p.unit_price_unit)


def need_for(item: Item) -> Amount | None:
    """The item's need in base units; spoon measures of a spice/sauce mean one jar.

    Outside Kryddor & Såser a spoon measure stays in ml, and `choose` falls back to one
    package only for offers the ml can't be converted to (tomatpuré sold by weight).
    """
    if item.amount is None or item.unit is None:
        return None
    if item.unit.lower() in SPOON_UNITS and item.category.casefold() == SPICE_CATEGORY:
        return Amount(1, "förp")
    return to_base(item.amount, item.unit)


def _need_out(item: Item) -> Need:
    need = need_for(item)
    if need is not None:
        return Need(need.value, need.dim)
    if item.amount is None or item.unit is None:
        return Need(None, None)
    return Need(item.amount, item.unit)


def _unit_price(p: Product) -> str | None:
    if p.gross_unit_price is None or not p.unit_price_unit:
        return None
    return f"{p.gross_unit_price:.2f} kr/{p.unit_price_unit}"


def _deal(p: Product) -> str | None:
    pricing = parse_pricing(p)
    titles = [d.title for d in pricing.deals] + list(pricing.informational)
    return ", ".join(titles) or None


def candidate_view(p: Product) -> Candidate:
    return Candidate(product_id=p.id, name=p.full_name, package=p.name_extra or "", price=p.gross_price,
                     unit_price=_unit_price(p), deal=_deal(p))


@dataclass
class Settled:
    decided: dict[str, PlanLine | Undecided] = field(default_factory=dict)   # vara_id -> result
    pending: list[Pending] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)                           # every non-skipped vara_id
    excluded: list[str] = field(default_factory=list)   # bought elsewhere, e.g. "ljus lager (köps på Systembolaget)"
    items: dict[str, Item] = field(default_factory=dict)


class Planner:
    def __init__(self, deps: PlannerDeps):
        self.deps = deps
        self.warnings: list[str] = []
        self.offers: dict[int, Offer] = {}     # chosen offer per product id, for per-product limits

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        self.deps.warn(message)

    def bought_elsewhere(self, item: Item) -> str | None:
        return self.deps.rules.bought_elsewhere(item.name)

    def term_for(self, item: Item) -> str:
        pin = self.deps.pins.get(item.key)
        return pin.search if pin and pin.search else item.key

    def candidates_for(self, item: Item, term: str) -> list[Product]:
        kept, _ = filter_candidates(self.deps.search(term), self.deps.rules.rule_for(item.name, item.category))
        return agent_order(kept)

    def undecided_for(self, item: Item, reason: str, products: Sequence[Product],
                      note: str | None = None) -> Undecided:
        return Undecided(item=item.name, need=_need_out(item), category=item.category, reason=reason,
                         candidates=[candidate_view(p) for p in list(products)[:SHOWN_CANDIDATES]], note=note)

    def _resolve(self, product_id: int, raw: Sequence[Product]) -> Product | None:
        found = next((p for p in raw if p.id == product_id), None)
        return found if found is not None else self.deps.lookup(product_id)

    def settle(self, item: Item, vid: str) -> PlanLine | Undecided | Pending:
        pin = self.deps.pins.get(item.key)
        term = self.term_for(item)
        raw = self.deps.search(term)
        kept, _ = filter_candidates(raw, self.deps.rules.rule_for(item.name, item.category))
        if need_for(item) is None:
            reason = AMOUNT_MISSING if item.amount is None or item.unit is None else UNKNOWN_UNIT
            return self.undecided_for(item, reason, kept)
        if pin and pin.fixed is not None:
            # Pins bypass the category filter, never availability.
            product = self._resolve(pin.fixed, raw)
            if product is None or not product.available:
                return self.undecided_for(item, "fast produkt ej tillgänglig", kept)
            return self.line_for(item, [product], "fast")
        if pin and pin.approved:
            found = [self._resolve(pid, raw) for pid in pin.approved]
            accepted = [p for p in found if p is not None and p.available]
            if accepted:
                return self.line_for(item, accepted, "pin")
            self.warn(f"{item.name}: ingen godkänd produkt är tillgänglig ({', '.join(map(str, pin.approved))})")
        return Pending(item=item, vara_id=vid, term=term, products=agent_order(kept))

    def line_for(self, item: Item, accepted: Sequence[Product], decision: str,
                 reason: str | None = None) -> PlanLine | Undecided:
        rules = self.deps.rules
        rule = rules.for_category(item.category)
        need = need_for(item)
        if need is None:
            return self.undecided_for(item, AMOUNT_MISSING, accepted, reason)
        offers = [o for p in accepted if (o := to_offer(p))]
        stock_up = rules.stock_up_for(item.name, item.category)
        choice = choose(need, offers, max_overshoot=None if stock_up else rule.overshoot_cap(),
                        convert=lambda a, d, o: convert(a, d, item.key, rules.conversions, product=o.name,
                                                        package=o.package.size),
                        spoon_measure=(item.unit or "").lower() in SPOON_UNITS,
                        stock_up=stock_up)
        if choice.option is None:
            return self.undecided_for(item, choice.reason or "ingen förpackning går att räkna", accepted, reason)
        option = choice.option
        product = next(p for p in accepted if p.id == option.offer.product_id)
        self.offers[product.id] = option.offer
        flags = list(option.flags)
        if item.verify:
            flags.append("verifiera")
        if decision not in USER_DECISIONS and not meets_preference(product, rule):
            flags.append("ej föredragen")  # nothing preferred was available; pins are the user's choice
        if option.count > rules.max_count_per_line:
            flags.append("för_många")
        return PlanLine(item=item.name, need=_need_out(item), category=item.category, product_id=product.id,
                        name=product.full_name, package=product.name_extra or "", count=option.count,
                        cost_kr=option.cost, unit_price=_unit_price(product), deal=_deal(product),
                        overshoot=option.overshoot, decision=decision, flags=flags, reason=reason)

    def apply_answer(self, item: Item, answer: Answer) -> bool:
        """Save the answer as a pin. False when the answer can't be used (keep the Undecided)."""
        pins = self.deps.pins
        if answer.kind == "accept" and answer.product_id is not None:
            pins.approve(item.key, answer.product_id)
        elif answer.kind == "fixed" and answer.product_id is not None:
            pins.set_fixed(item.key, answer.product_id)
        elif answer.kind == "search" and answer.term and answer.term.strip():
            pins.set_search(item.key, answer.term)
        else:
            return False
        pins.save()
        return True

    def ask(self, item: Item, vid: str, first: Undecided, asker: Asker) -> PlanLine | Undecided | None:
        """Ask until a pin settles the item, the user skips it (None), or MAX_QUESTIONS answers."""
        result = first
        for _ in range(MAX_QUESTIONS):
            answer = asker.ask(item, result.candidates)
            if answer.kind == "skip":
                return None
            if not self.apply_answer(item, answer):
                return result
            settled = self.settle(item, vid)
            if isinstance(settled, Pending):
                reason = "välj produkt" if settled.products else NO_CANDIDATES
                settled = self.undecided_for(item, reason, settled.products)
            if isinstance(settled, PlanLine):
                return settled
            result = settled
        return result

    def finish(self, *, week: str, now: datetime, outcomes: Sequence[PlanLine | Undecided],
               skipped: Sequence[str], excluded: Sequence[str]) -> Plan:
        lines = [o for o in outcomes if isinstance(o, PlanLine)]
        open_items = [o for o in outcomes if isinstance(o, Undecided)]
        lines, over_limit = _share_limits(lines, self.offers)
        open_items.extend(over_limit)
        return Plan(week=week, created=now, lines=lines, undecided=open_items, skipped=list(skipped),
                    excluded=list(excluded), warnings=list(self.warnings),
                    total_kr=round(sum(line.cost_kr for line in lines), 2))


def _share_limits(lines: list[PlanLine], offers: dict[int, Offer]) -> tuple[list[PlanLine], list[Undecided]]:
    """Apply per-customer limits and discount pricing per product, not per line (Q5).

    `choose` sees one line at a time, so two items resolved to the same product could
    each fit "Max N per kund" and each price its units at the discounted rate. A line
    that would take the product past its limit becomes undecided; later lines are
    priced as the next units of the same product.
    """
    kept: list[PlanLine] = []
    moved: list[Undecided] = []
    taken: dict[int, int] = {}
    first_item: dict[int, str] = {}
    for line in lines:
        pid, offer = line.product_id, offers.get(line.product_id)
        before = taken.get(pid, 0)
        limit = offer.package.max_count if offer else None
        if before and limit is not None and before + line.count > limit:
            moved.append(Undecided(item=line.item, need=line.need, category=line.category,
                                   reason=f"max antal per kund räcker inte (delas med {first_item[pid]})"))
            continue
        if before and offer is not None:
            pr = offer.pricing
            args = (offer.price, pr.deals, pr.discount_limit, pr.undiscounted_price)
            line = replace(line, cost_kr=round(cost_for(before + line.count, *args) - cost_for(before, *args), 2))
        taken[pid] = before + line.count
        first_item.setdefault(pid, line.item)
        kept.append(line)
    return kept, moved


def settle_all(shopping: ShoppingList, planner: Planner, skip: Collection[str] = ()) -> Settled:
    skip_keys = {normalize_key(s) for s in skip}
    settled = Settled()
    for position, item in enumerate(shopping.items, 1):
        vid = vara_id(position)
        if item.key in skip_keys:
            settled.skipped.append(item.name)
            continue
        place = planner.bought_elsewhere(item)
        if place is not None:
            settled.excluded.append(f"{item.name} (köps på {place})")
            continue
        settled.order.append(vid)
        settled.items[vid] = item
        result = planner.settle(item, vid)
        if isinstance(result, Pending):
            settled.pending.append(result)
        else:
            settled.decided[vid] = result
    return settled
