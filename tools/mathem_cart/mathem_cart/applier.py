"""Execute a saved plan verbatim against the Mathem cart, then verify it (spec §8, §11).

`check_safety` needs no network and is called by the CLI before login; `apply_plan`
calls it again, refuses a non-empty cart before any add, adds every planned line in
order, reads the cart back and compares. A partial failure never raises: it is
reported in `ApplyResult.error` / `ApplyResult.differences` and the CLI exits 1.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable, Protocol

from .mathem.errors import MathemAuthError, MathemRequestError
from .mathem.models import Cart
from .plan_model import ApplyResult, Plan
from .report import fmt_kr, fmt_num
from .rules import Rules

FUTURE_TOLERANCE = timedelta(minutes=5)
TOTAL_TOLERANCE_KR = 0.01   # the planner rounds the sum to öre
LOGIN_EXPIRED = "inloggningen gick ut — logga in igen / kontrollera .env"


class SafetyAbort(Exception):
    """A safety check failed; nothing was added to the cart."""


class CartLike(Protocol):
    def get(self) -> Cart: ...

    def add(self, product_id: int, quantity: int) -> Cart: ...


def _aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.utcoffset() is not None


def check_safety(plan: Plan, rules: Rules, now: datetime) -> None:
    """Raise SafetyAbort if the plan must not be applied. No network."""
    if not _aware(now):
        raise SafetyAbort("aktuell tid saknar tidszon")
    if not _aware(plan.created):
        raise SafetyAbort("planens tidsstämpel saknar tidszon — kör plan igen")
    # A YAML .nan would disable the age limit (nan > x is False) and .inf crashes timedelta.
    if not math.isfinite(rules.plan_max_age_h) or rules.plan_max_age_h <= 0:
        raise SafetyAbort(f"säkerhet.plan_max_ålder_h måste vara ett positivt tal, inte {rules.plan_max_age_h}")
    if now - plan.created > timedelta(hours=rules.plan_max_age_h):
        raise SafetyAbort(f"planen är äldre än {fmt_num(rules.plan_max_age_h)} h — kör plan igen")
    if plan.created - now > FUTURE_TOLERANCE:
        raise SafetyAbort("planen är daterad i framtiden")
    # The stored total is only a claim: the lines are what gets added, so a total
    # that disagrees with their sum means an edited plan.
    for line in plan.lines:
        if not math.isfinite(line.cost_kr) or line.cost_kr < 0:
            raise SafetyAbort(f"{line.item}: ogiltig kostnad {line.cost_kr} — kör plan igen")
    total = sum(line.cost_kr for line in plan.lines)
    if not math.isfinite(plan.total_kr) or abs(total - plan.total_kr) > TOTAL_TOLERANCE_KR:
        raise SafetyAbort(f"planens total {plan.total_kr} stämmer inte med raderna ({fmt_kr(total)}) "
                          "— kör plan igen")
    for line in plan.lines:
        if line.count > rules.max_count_per_line:
            raise SafetyAbort(f"{line.item}: {line.count} st överstiger gränsen "
                              f"{rules.max_count_per_line} per rad (säkerhet.max_antal_per_rad)")
        if line.count < 1:
            raise SafetyAbort(f"{line.item}: antal måste vara minst 1, inte {line.count}")


def _counts(cart: Cart) -> dict[int, int]:
    counts: dict[int, int] = {}
    for cl in cart.lines:
        counts[cl.product_id] = counts.get(cl.product_id, 0) + cl.quantity
    return counts


def apply_plan(plan: Plan, cart: CartLike, rules: Rules, *, now: datetime,
               relogin: Callable[[], None] | None = None) -> ApplyResult:
    check_safety(plan, rules, now)
    before = cart.get()
    if not before.is_empty:
        raise SafetyAbort(f"varukorgen är inte tom ({len(before.lines)} rader) — töm den på "
                          "mathem.se och kör apply igen")

    expected: dict[int, int] = {}
    names: dict[int, str] = {}
    for line in plan.lines:
        expected[line.product_id] = expected.get(line.product_id, 0) + line.count
        names.setdefault(line.product_id, line.name)

    differences: list[str] = []
    failed_add: set[int] = set()
    error: str | None = None
    relogin_used = False

    for line in plan.lines:
        label = f"{line.name} ({line.product_id})"
        while True:
            try:
                cart.add(line.product_id, line.count)
            except MathemAuthError:
                if relogin is not None and not relogin_used:
                    relogin_used = True
                    try:
                        relogin()
                    except Exception:  # noqa: BLE001 — any relogin failure means stop
                        error = LOGIN_EXPIRED
                        break
                    continue  # retry the same line once
                error = LOGIN_EXPIRED
            except MathemRequestError as exc:
                # 429 is about the whole session, not this product: stop.
                if 400 <= exc.status < 500 and exc.status != 429:
                    differences.append(f"{label}: kunde inte läggas till (HTTP {exc.status})")
                    failed_add.add(line.product_id)
                else:
                    error = f"avbröts vid {line.name}: {exc}"
            except Exception as exc:  # noqa: BLE001 — stop, then report what got in
                error = f"avbröts vid {line.name}: {exc}"
            break
        if error is not None:
            break

    try:
        after = cart.get()
    except Exception as exc:  # noqa: BLE001 — best effort read-back
        msg = f"varukorgen kunde inte läsas tillbaka ({exc}) — kontrollera den på mathem.se"
        error = msg if error is None else f"{error}; {msg}"
        return ApplyResult(now, expected, {}, differences, error)

    actual = _counts(after)
    unavailable = {cl.product_id for cl in after.lines if cl.available is False}
    for pid, want in expected.items():
        label = f"{names[pid]} ({pid})"
        got = actual.get(pid, 0)
        if got == 0:
            if pid not in failed_add:
                differences.append(f"{label}: saknas i varukorgen")
        elif got != want:
            differences.append(f"{label}: {got} st i stället för {want}")
        if got and pid in unavailable:
            differences.append(f"{label}: finns men är inte tillgänglig")
    for cl in after.lines:
        if cl.product_id not in expected:
            differences.append(f"oväntad rad: {cl.name} ({cl.product_id}), {cl.quantity} st")

    return ApplyResult(now, expected, actual, differences, error)
