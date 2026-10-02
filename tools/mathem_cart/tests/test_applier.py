from datetime import datetime, timedelta, timezone

import pytest

from mathem_cart.applier import SafetyAbort, apply_plan, check_safety
from mathem_cart.mathem.errors import MathemAuthError, MathemRequestError
from mathem_cart.mathem.models import Cart, CartLine
from mathem_cart.plan_model import Need, Plan, PlanLine
from mathem_cart.rules import parse_rules

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 9, 24, 18, 0, tzinfo=TZ)
RULES = parse_rules({})


def line(pid, count=1, cost=10.0, item=None):
    return PlanLine(item or f"vara{pid}", Need(1, "st"), "Övrigt", pid, f"Produkt {pid}", "1 st", count,
                    cost, None, None, 0.0, "pin", [])


def plan(lines, created=NOW - timedelta(minutes=5)):
    return Plan("2026-09-21", created, lines, [], [], [], [], round(sum(l.cost_kr for l in lines), 2))


class FakeCart:
    def __init__(self, initial=(), fail_on=None, unavailable=()):
        self.qty = {pid: q for pid, q in initial}
        self.adds = []
        self.fail_on = fail_on or {}
        self.unavailable = set(unavailable)

    def _cart(self):
        return Cart(tuple(CartLine(pid, f"Produkt {pid}", q, pid not in self.unavailable)
                          for pid, q in self.qty.items() if q))

    def get(self):
        return self._cart()

    def add(self, pid, q):
        exc = self.fail_on.get(pid)
        if exc:
            if isinstance(exc, list):
                exc = exc.pop(0) if exc else None
            if exc:
                raise exc
        self.adds.append((pid, q))
        self.qty[pid] = self.qty.get(pid, 0) + q
        return self._cart()


def test_happy_path():
    cart = FakeCart()
    result = apply_plan(plan([line(1, 2), line(2)]), cart, RULES, now=NOW)
    assert result.ok and cart.adds == [(1, 2), (2, 1)] and result.actual == {1: 2, 2: 1}


def test_non_empty_cart_aborts_before_adding():
    cart = FakeCart(initial=[(99, 1)])
    with pytest.raises(SafetyAbort, match="inte tom"):
        apply_plan(plan([line(1)]), cart, RULES, now=NOW)
    assert cart.adds == []


def test_stale_plan_aborts():
    with pytest.raises(SafetyAbort, match="äldre än 24"):
        check_safety(plan([line(1)], created=NOW - timedelta(hours=25)), RULES, NOW)


def test_future_plan_aborts():
    with pytest.raises(SafetyAbort, match="framtiden"):
        check_safety(plan([line(1)], created=NOW + timedelta(hours=1)), RULES, NOW)


def test_large_total_is_not_limited():
    check_safety(plan([line(1, cost=4000.0)]), RULES, NOW)


def test_count_limit_aborts():
    with pytest.raises(SafetyAbort, match="vara1"):
        check_safety(plan([line(1, count=11)]), RULES, NOW)


def test_same_product_on_two_lines_is_summed():
    # Review Focus 3
    result = apply_plan(plan([line(1, 2, item="gul lök"), line(1, 1, item="gul lök (sallad)")]), FakeCart(), RULES, now=NOW)
    assert result.ok and result.expected == {1: 3} and result.actual == {1: 3}


def test_partial_failure_reports_what_got_in():
    cart = FakeCart(fail_on={2: RuntimeError("anslutningen bröts")})
    result = apply_plan(plan([line(1), line(2), line(3)]), cart, RULES, now=NOW)
    assert cart.adds == [(1, 1)]
    assert result.actual == {1: 1} and "anslutningen bröts" in result.error
    assert any("Produkt 2 (2): saknas" in d for d in result.differences)


def test_unavailable_product_is_a_difference_and_rest_is_added():
    cart = FakeCart(fail_on={2: MathemRequestError(400, "POST", "/api/v1/cart/items/")})
    result = apply_plan(plan([line(1), line(2), line(3)]), cart, RULES, now=NOW)
    assert cart.adds == [(1, 1), (3, 1)] and result.error is None
    assert any("kunde inte läggas till (HTTP 400)" in d for d in result.differences)


def test_rate_limit_stops_instead_of_skipping_the_rest():
    cart = FakeCart(fail_on={2: MathemRequestError(429, "POST", "/api/v1/cart/items/")})
    result = apply_plan(plan([line(1), line(2), line(3)]), cart, RULES, now=NOW)
    assert cart.adds == [(1, 1)]
    assert result.error is not None and "429" in result.error
    assert not any("kunde inte läggas till" in d for d in result.differences)


def test_relogin_once_then_continue():
    calls = []
    cart = FakeCart(fail_on={1: [MathemAuthError("401")]})
    result = apply_plan(plan([line(1)]), cart, RULES, now=NOW, relogin=lambda: calls.append(1))
    assert calls == [1] and result.ok


def test_second_auth_error_stops():
    cart = FakeCart(fail_on={1: [MathemAuthError("401"), MathemAuthError("401")]})
    result = apply_plan(plan([line(1)]), cart, RULES, now=NOW, relogin=lambda: None)
    assert "logga in igen" in result.error


def test_wrong_count_and_unavailable_in_cart_are_differences():
    class Weird(FakeCart):
        def add(self, pid, q):
            super().add(pid, q - 1 if pid == 1 else q)
            return self._cart()
    cart = Weird(unavailable={2})
    result = apply_plan(plan([line(1, 3), line(2)]), cart, RULES, now=NOW)
    assert any("2 st i stället för 3" in d for d in result.differences)
    assert any("inte tillgänglig" in d for d in result.differences)


def test_naive_now_aborts():
    with pytest.raises(SafetyAbort):
        check_safety(plan([line(1)]), RULES, datetime(2026, 9, 24, 18, 0))


def test_non_positive_count_aborts():
    with pytest.raises(SafetyAbort, match="vara1"):
        check_safety(plan([line(1, count=0)]), RULES, NOW)


def test_unexpected_line_after_apply_is_a_difference():
    class Extra(FakeCart):
        def add(self, pid, q):
            super().add(pid, q)
            self.qty[77] = 1
            return self._cart()
    result = apply_plan(plan([line(1)]), Extra(), RULES, now=NOW)
    assert any(d.startswith("oväntad rad:") and "(77)" in d for d in result.differences)


def test_failed_read_back_sets_error_without_raising():
    class Flaky(FakeCart):
        gets = 0

        def get(self):
            self.gets += 1
            if self.gets > 1:
                raise RuntimeError("timeout")
            return super().get()
    cart = Flaky()
    result = apply_plan(plan([line(1)]), cart, RULES, now=NOW)
    assert cart.adds == [(1, 1)] and result.actual == {}
    assert "kunde inte läsas tillbaka" in result.error and not result.ok


def test_auth_error_without_relogin_stops():
    cart = FakeCart(fail_on={1: [MathemAuthError("401")]})
    result = apply_plan(plan([line(1), line(2)]), cart, RULES, now=NOW)
    assert cart.adds == [] and "logga in igen" in result.error


def test_total_is_recomputed_from_lines_not_trusted():
    # S1: an edited plan whose stored total disagrees with its lines must not pass.
    edited = plan([line(1, 10, cost=2000.0), line(2, 10, cost=2000.0)])
    edited.total_kr = 10.0
    with pytest.raises(SafetyAbort):
        check_safety(edited, RULES, NOW)


def test_stored_total_that_disagrees_with_lines_aborts_even_under_limit():
    edited = plan([line(1, cost=100.0)])
    edited.total_kr = 50.0
    with pytest.raises(SafetyAbort, match="stämmer inte"):
        check_safety(edited, RULES, NOW)


@pytest.mark.parametrize("field", ["total", "cost"])
def test_nan_total_or_cost_aborts(field):
    p = plan([line(1, cost=99999.0)])
    if field == "total":
        p.total_kr = float("nan")
    else:
        p.lines[0].cost_kr = float("nan")
        p.total_kr = 0.0
    with pytest.raises(SafetyAbort):
        check_safety(p, RULES, NOW)


def test_negative_cost_aborts():
    p = plan([line(1, cost=4000.0), line(2, cost=-1500.0)])
    with pytest.raises(SafetyAbort, match="vara2"):
        check_safety(p, RULES, NOW)


@pytest.mark.parametrize("limits", [{"plan_max_age_h": float("nan")},
                                    {"plan_max_age_h": float("inf")}, {"plan_max_age_h": -1.0}])
def test_non_finite_or_non_positive_limits_abort(limits):
    from dataclasses import replace
    with pytest.raises(SafetyAbort):
        check_safety(plan([line(1)]), replace(RULES, **limits), NOW)
