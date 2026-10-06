import pytest

from mathem_cart.packaging import Deal, Package, Pricing
from mathem_cart.quantity import Offer, StockUp, choose, cost_for
from mathem_cart.units import Amount


def offer(pid, grams, price, unit_price=None, max_count=None, deals=(), approximate=False,
          limit=None, undiscounted=None, dim="g", flags=()):
    return Offer(pid, f"vara {pid}", price, unit_price,
                 Package(Amount(grams, dim), max_count, approximate, flags),
                 Pricing(tuple(deals), (), limit, undiscounted))


def test_spec_example_two_small_packs_beat_two_big():
    # 1,2 kg chicken -> 2 x 700 g at 60,95 = 121,90 kr, not 2 x 1000 g.
    small, big = offer(1, 700, 60.95, 87.07), offer(2, 1000, 89.95, 89.95)
    choice = choose(Amount(1200, "g"), [big, small], max_overshoot=None)
    assert choice.option.offer.product_id == 1
    assert choice.option.count == 2
    assert choice.option.cost == pytest.approx(121.90)
    assert choice.option.overshoot == pytest.approx(200 / 1200, abs=1e-4)


def test_multibuy_deal_wins():
    kronfagel = offer(1, 700, 72.50, 103.57, max_count=2, deals=[Deal(2, 99.0, "2 för 99 kr")])
    garant = offer(2, 700, 60.95, 87.07)
    choice = choose(Amount(1200, "g"), [garant, kronfagel], max_overshoot=None)
    assert choice.option.offer.product_id == 1 and choice.option.cost == pytest.approx(99.0)


def test_max_count_drops_offer_that_cannot_cover_need():
    limited = offer(1, 700, 30.0, max_count=2)       # 2100 g needs 3
    other = offer(2, 1000, 70.0)
    choice = choose(Amount(2100, "g"), [limited, other], max_overshoot=None)
    assert choice.option.offer.product_id == 2 and choice.option.count == 3


def test_overshoot_cap_prefers_closer_package():
    kilo, small = offer(1, 1000, 19.90), offer(2, 350, 22.00)
    choice = choose(Amount(300, "g"), [kilo, small], max_overshoot=0.25)
    assert choice.option.offer.product_id == 2
    assert "överköp" not in choice.option.flags


def test_frysbar_has_no_cap():
    kilo, small = offer(1, 1000, 19.90), offer(2, 350, 22.00)
    assert choose(Amount(300, "g"), [kilo, small], max_overshoot=None).option.offer.product_id == 1


def test_all_over_cap_picks_smallest_overshoot_and_flags():
    kilo, half = offer(1, 1000, 19.90), offer(2, 500, 12.00)
    choice = choose(Amount(300, "g"), [kilo, half], max_overshoot=0.25)
    assert choice.option.offer.product_id == 2 and "överköp" in choice.option.flags


def test_tie_breaks_on_unit_price_then_overshoot():
    a = offer(1, 500, 20.0, unit_price=40.0)
    b = offer(2, 500, 20.0, unit_price=38.0)
    assert choose(Amount(400, "g"), [a, b], max_overshoot=None).option.offer.product_id == 2


def test_package_count_need():
    choice = choose(Amount(2, "förp"), [offer(1, 500, 15.0), offer(2, 1000, 25.0)], max_overshoot=0.25)
    assert (choice.option.offer.product_id, choice.option.count, choice.option.overshoot) == (1, 2, 0.0)


def test_converter_is_used_across_dimensions():
    per_piece = offer(1, 1, 5.0, dim="st")
    convert = lambda amount, dim, offer: Amount(amount.value / 150, "st") if dim == "st" else None
    choice = choose(Amount(450, "g"), [per_piece], max_overshoot=None, convert=convert)
    assert choice.option.count == 3


def test_no_usable_offer_gives_reason():
    unusable = Offer(1, "x", 10.0, None, Package(None), Pricing())
    choice = choose(Amount(300, "g"), [unusable], max_overshoot=None)
    assert choice.option is None and choice.reason == "ingen förpackning går att räkna"


def test_offer_without_price_is_skipped_not_a_crash():
    # Review Focus 5: a product with gross_price null is skipped.
    no_price = offer(1, 500, None)
    priced = offer(2, 500, 30.0)
    assert choose(Amount(400, "g"), [no_price, priced], max_overshoot=None).option.offer.product_id == 2
    alone = choose(Amount(400, "g"), [no_price], max_overshoot=None)
    assert alone.option is None and alone.reason == "ingen förpackning går att räkna"


def test_only_max_count_blockers_gives_specific_reason():
    choice = choose(Amount(5000, "g"), [offer(1, 700, 30.0, max_count=2)], max_overshoot=None)
    assert choice.option is None and choice.reason == "max antal per kund räcker inte"


def test_approximate_and_package_flags_propagate():
    choice = choose(Amount(400, "g"), [offer(1, 430, 150.77, approximate=True, flags=("storlek_osäker",))],
                    max_overshoot=None)
    assert set(choice.option.flags) == {"ungefärlig", "storlek_osäker"}


def test_exact_multiple_has_no_float_drift():
    assert choose(Amount(1500, "ml"), [offer(1, 500, 10.0, dim="ml")], max_overshoot=0).option.count == 3


@pytest.mark.parametrize("count,expected", [(1, 72.50), (2, 99.0), (3, 171.50), (4, 198.0)])
def test_cost_for_multibuy(count, expected):
    assert cost_for(count, 72.50, [Deal(2, 99.0, "2 för 99 kr")]) == pytest.approx(expected)


def test_cost_for_discount_limit():
    # -10 % on max 2: units 3 and 4 at the undiscounted price
    assert cost_for(4, 59.58, (), discount_limit=2, undiscounted_price=66.20) == pytest.approx(251.56)


def test_deal_that_is_not_cheaper_is_ignored():
    assert cost_for(2, 10.0, [Deal(2, 25.0, "2 för 25 kr")]) == pytest.approx(20.0)


@pytest.mark.parametrize("need,count,cost", [(0.5, 1, 15.0), (2, 2, 30.0)])
def test_package_count_need_does_not_require_a_size(need, count, cost):
    # Q3 / V5: "½ knippe dill" against a product sold as "Knippe" (no parseable size).
    unsized = Offer(1, "Dill", 15.0, None, Package(None), Pricing())
    choice = choose(Amount(need, "förp"), [unsized], max_overshoot=0.25)
    assert (choice.option.count, choice.option.cost) == (count, cost)


def test_package_count_need_still_skips_unpriced_offer():
    no_price = Offer(1, "Dill", None, None, Package(None), Pricing())
    assert choose(Amount(1, "förp"), [no_price], max_overshoot=0.25).option is None


@pytest.mark.parametrize("count,expected", [(2, 99.0), (3, 171.50), (4, 244.0)])
def test_multibuy_deal_applies_within_discount_limit(count, expected):
    # Q4: fixture product 66316 — "2 för 99 kr", maximum_quantity 2, undiscounted 72,50.
    deal = (Deal(2, 99.0, "2 för 99 kr"),)
    assert cost_for(count, 72.5, deal, discount_limit=2, undiscounted_price=72.5) == pytest.approx(expected)


STOCK = StockUp(max_extra_share=0.5, max_extra_kr=100)


def test_stock_up_picks_lowest_jamforpris_within_the_spend_cap():
    # 1,5 kg chicken: 2 x 900 g for 238 kr vs 2,5 kg for 249 kr (+11 kr, far cheaper per kg).
    small, big = offer(1, 900, 119.0, 132.2), offer(2, 2500, 249.0, 99.6)
    choice = choose(Amount(1500, "g"), [small, big], max_overshoot=None, stock_up=STOCK)
    assert choice.option.offer.product_id == 2 and choice.option.count == 1
    assert "storpack" in choice.option.flags
    assert choose(Amount(1500, "g"), [small, big], max_overshoot=None).option.offer.product_id == 1


def test_stock_up_respects_the_smaller_of_share_and_kronor():
    # 400 g mince: 1 kg costs 40 kr (68 %) more than 500 g -> over the 50 % share.
    half, kilo = offer(1, 500, 59.0, 118.0), offer(2, 1000, 99.0, 99.0)
    assert choose(Amount(400, "g"), [half, kilo], max_overshoot=None, stock_up=STOCK).option.offer.product_id == 1
    # 300 kr baseline: 50 % would be 150 kr, but the 100 kr cap wins.
    base, bulk = offer(3, 3000, 300.0, 100.0), offer(4, 6000, 420.0, 70.0)
    assert choose(Amount(3000, "g"), [base, bulk], max_overshoot=None,
                  stock_up=STOCK).option.offer.product_id == 3
    assert choose(Amount(3000, "g"), [base, bulk], max_overshoot=None,
                  stock_up=StockUp(0.5, 150)).option.offer.product_id == 4


def test_stock_up_uses_effective_unit_cost_so_deals_count():
    # Listed jämförpris says A (90 kr/kg) but "2 för 150" makes B cheaper per kg bought.
    a = offer(1, 1000, 90.0, 90.0)
    b = offer(2, 1000, 100.0, 100.0, deals=[Deal(2, 150.0, "2 för 150 kr")])
    choice = choose(Amount(1800, "g"), [a, b], max_overshoot=None, stock_up=STOCK)
    assert choice.option.offer.product_id == 2 and choice.option.cost == pytest.approx(150.0)
    assert "storpack" not in choice.option.flags     # it is also the cheapest


def test_stock_up_ignores_the_overshoot_cap_and_falls_back_to_cost_without_sizes():
    kilo, small = offer(1, 1000, 19.90), offer(2, 350, 22.00)
    assert choose(Amount(300, "g"), [kilo, small], max_overshoot=None,
                  stock_up=STOCK).option.offer.product_id == 1
    jar = lambda pid, price, unit: Offer(pid, "burk", price, unit, Package(None), Pricing())
    choice = choose(Amount(1, "förp"), [jar(1, 30.0, 300.0), jar(2, 40.0, 200.0)], max_overshoot=None,
                    stock_up=STOCK)
    assert choice.option.offer.product_id == 2      # förp: Mathem's jämförpris decides


def _jar(pid, price, unit_price, unit):
    return Offer(pid, f"burk {pid}", price, unit_price, Package(None), Pricing(), unit)


def test_stock_up_never_compares_jamforpris_across_units():
    # Review: "1 tsk spiskummin" (one package). 22 kr/st must not beat 300 kr/kg.
    jar, bag = _jar(1, 22.0, 22.0, "st"), _jar(2, 30.0, 300.0, "kg")
    choice = choose(Amount(1, "förp"), [jar, bag], max_overshoot=None, stock_up=STOCK)
    assert choice.option.offer.product_id == 1 and "storpack" not in choice.option.flags  # cheapest, no jmf
    # Same with the units the other way round: no comparison, so no pricier pick.
    a, b = _jar(3, 25.0, 625.0, "kg"), _jar(4, 29.0, 29.0, "st")
    choice = choose(Amount(1, "förp"), [a, b], max_overshoot=None, stock_up=STOCK)
    assert choice.option.offer.product_id == 3 and "storpack" not in choice.option.flags


def test_stock_up_compares_within_the_majority_unit():
    small, big, odd = _jar(1, 25.0, 1000.0, "kg"), _jar(2, 35.0, 350.0, "kg"), _jar(3, 24.0, 24.0, "st")   # cheapest: cap 24 + 12 kr
    choice = choose(Amount(1, "förp"), [small, big, odd], max_overshoot=None, stock_up=STOCK)
    assert choice.option.offer.product_id == 2 and "storpack" in choice.option.flags


STAPLE = StockUp(max_extra_share=None, max_extra_kr=150, min_saving=0.15)


def test_staples_buy_the_big_sack_that_a_share_of_a_cheap_bag_never_allows():
    # 1 kg potatis: 1 kg for 20 kr, 2 kg for 32 kr, 5 kg for 59 kr. Storpack's 50 % (10 kr) keeps the bag.
    bag, two, sack = offer(1, 1000, 20.0, 20.0), offer(2, 2000, 32.0, 16.0), offer(3, 5000, 59.0, 11.8)
    assert choose(Amount(1000, "g"), [bag, two, sack], max_overshoot=None,
                  stock_up=STOCK).option.offer.product_id == 1
    choice = choose(Amount(1000, "g"), [bag, two, sack], max_overshoot=None, stock_up=STAPLE)
    assert choice.option.offer.product_id == 3 and "storpack" in choice.option.flags
    # The kronor cap still holds: 150 kr over 20 kr is 170 kr.
    huge = offer(4, 25000, 199.0, 7.96)
    assert choose(Amount(1000, "g"), [bag, huge], max_overshoot=None,
                  stock_up=STAPLE).option.offer.product_id == 1


def test_staples_respect_the_max_amount_unless_the_need_is_bigger():
    bag, two, sack = offer(1, 1000, 20.0, 20.0), offer(2, 2000, 32.0, 16.0), offer(3, 5000, 59.0, 11.8)
    capped = StockUp(None, 150, 0.15, Amount(3000, "g"))
    assert choose(Amount(1000, "g"), [bag, two, sack], max_overshoot=None,
                  stock_up=capped).option.offer.product_id == 2
    # Needing 6 kg: the cheapest way already exceeds 3 kg and is always allowed.
    choice = choose(Amount(6000, "g"), [bag, sack], max_overshoot=None, stock_up=capped)
    assert choice.option is not None and choice.option.cost == pytest.approx(min(6 * 20.0, 2 * 59.0))


def test_staples_keep_the_cheapest_when_the_saving_is_too_small():
    # 1 kg ris 30 kr vs 5 kg for 140 kr (28 kr/kg, 7 % cheaper): not worth 4 kg in the cupboard.
    kilo, five = offer(1, 1000, 30.0, 30.0), offer(2, 5000, 140.0, 28.0)
    choice = choose(Amount(500, "g"), [kilo, five], max_overshoot=None, stock_up=STAPLE)
    assert choice.option.offer.product_id == 1 and "storpack" not in choice.option.flags


def test_staples_never_buy_more_than_the_max_multiple_of_the_need():
    # 1 dl ris (85 g): a 10 kg sack is 32 % cheaper per kg and within 150 kr, but 117 x the need.
    kilo, sack = offer(1, 1000, 25.0, 25.0), offer(2, 10000, 169.0, 16.9)
    multiple = StockUp(None, 150, 0.15, max_multiple=20)
    assert choose(Amount(85, "g"), [kilo, sack], max_overshoot=None,
                  stock_up=multiple).option.offer.product_id == 1
    assert choose(Amount(600, "g"), [kilo, sack], max_overshoot=None,
                  stock_up=multiple).option.offer.product_id == 2      # 16,7 x: fine


def test_staples_drop_options_the_max_amount_cant_measure():
    # "lök: 3 kg", but the net is sold per piece: its amount can't be checked, so it's out.
    bag = offer(1, 1000, 20.0, 20.0)
    net = offer(2, 40, 60.0, 1.5, dim="st")
    capped = StockUp(None, 150, 0.0, Amount(3000, "g"))
    choice = choose(Amount(800, "g"), [bag, net], max_overshoot=None, stock_up=capped,
                    convert=lambda a, d, o: Amount(a.value / 150, "st") if d == "st" else a)
    assert choice.option.offer.product_id == 1 and "storpack" not in choice.option.flags


def test_staples_keep_the_cheapest_when_its_jamforpris_is_unknown():
    # Spoon fallback: the cheapest has no size, so no saving can be shown.
    unsized = Offer(1, "påse", 15.0, None, Package(None), Pricing())
    sack = offer(2, 2000, 60.0, 30.0, dim="ml")
    choice = choose(Amount(15, "ml"), [unsized, sack], max_overshoot=None, spoon_measure=True,
                    stock_up=StockUp(None, 150, 0.15))
    assert choice.option.offer.product_id == 1 and "storpack" not in choice.option.flags
