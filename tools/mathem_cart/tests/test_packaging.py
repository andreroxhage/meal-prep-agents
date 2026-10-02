import pytest

from mathem_cart.mathem.models import Product
from mathem_cart.packaging import Deal, parse_package, parse_pricing
from mathem_cart.units import Amount


def product(name_extra, price="10.00", unit_price=None, unit=None, promotions=(), discount=None):
    return Product.from_api({
        "id": 1, "full_name": "Testvara", "name_extra": name_extra, "gross_price": price,
        "gross_unit_price": unit_price, "unit_price_quantity_abbreviation": unit,
        "promotions": [{"title": t} for t in promotions], "discount": discount,
        "availability": {"is_available": True, "code": "available"},
    })


@pytest.mark.parametrize("extra,size", [
    ("5 dl", Amount(500, "ml")), ("2,5 dl", Amount(250, "ml")), ("1000 g", Amount(1000, "g")),
    ("1 kg", Amount(1000, "g")), ("1,5 l", Amount(1500, "ml")), ("33 cl", Amount(330, "ml")),
    ("250 ml", Amount(250, "ml")), ("3x400 g", Amount(1200, "g")), ("3 x 400 g", Amount(1200, "g")),
    ("6-pack", Amount(6, "st")), ("6 st", Amount(6, "st")),
])
def test_sizes(extra, size):
    pkg = parse_package(product(extra))
    assert pkg.size.dim == size.dim and pkg.size.value == pytest.approx(size.value)
    assert pkg.approximate is False and pkg.max_count is None


def test_approximate_weight():
    pkg = parse_package(product("ca 430 g"))
    assert pkg.size == Amount(430, "g") and pkg.approximate is True


@pytest.mark.parametrize("extra,size,max_count", [
    # Live 2026-09-24: produce carries its origin, ready meals a portion count, before the size.
    ("Sverige, 3000 g", Amount(3000, "g"), None),
    ("Europeiska unionen, 100 g", Amount(100, "g"), None),
    ("2 portioner, 500 g", Amount(500, "g"), None),
    ("Max 10 per kund, Zimbabwe, 165 g", Amount(165, "g"), 10),
])
def test_size_after_origin_or_other_prefix(extra, size, max_count):
    pkg = parse_package(product(extra))
    assert pkg.size == size and pkg.max_count == max_count and pkg.flags == ()


def test_max_per_customer_prefix():
    pkg = parse_package(product("Max 2 per kund, 700 g"))
    assert pkg.size == Amount(700, "g") and pkg.max_count == 2


def test_unit_price_fallback_when_name_extra_is_unparseable():
    pkg = parse_package(product("Klass 1", price="30.00", unit_price="60.00", unit="kg"))
    assert pkg.size.dim == "g" and pkg.size.value == pytest.approx(500)
    assert "storlek_från_jämförpris" in pkg.flags


def test_disagreement_over_five_percent_is_flagged():
    pkg = parse_package(product("500 g", price="30.00", unit_price="50.00", unit="kg"))  # implies 600 g
    assert pkg.size == Amount(500, "g") and "storlek_osäker" in pkg.flags


def test_agreement_within_five_percent_is_not_flagged():
    pkg = parse_package(product("5 dl", price="27.20", unit_price="54.40", unit="l"))
    assert pkg.flags == ()


def test_unit_price_in_other_dimension_is_ignored():
    # Live: Oatly iMat Visp, "250 ml", jämförpris per kg (Review Focus 4).
    pkg = parse_package(product("250 ml", price="20.35", unit_price="81.40", unit="kg"))
    assert pkg.size == Amount(250, "ml") and pkg.flags == ()


def test_unusable_without_size_or_fallback():
    assert parse_package(product("Klass 1")).size is None
    assert parse_package(product(None)).size is None


def test_multibuy_deal_in_kronor():
    pricing = parse_pricing(product("Max 2 per kund, 700 g", price="72.50", promotions=["2 för 99 kr"]))
    assert pricing.deals == (Deal(count=2, price=99.0, title="2 för 99 kr"),)


def test_n_for_m_units_deal():
    pricing = parse_pricing(product("400 g", price="12.00", promotions=["3 för 2"]))
    assert pricing.deals == (Deal(count=3, price=24.0, title="3 för 2"),)


def test_percent_discount_is_informational_because_gross_price_includes_it():
    pricing = parse_pricing(product("500 ml", price="59.58", promotions=["-10%", "Noga utvald"],
                                    discount={"is_discounted": True, "undiscounted_gross_price": "66.20",
                                              "maximum_quantity": None}))
    assert pricing.deals == ()
    assert pricing.informational == ("-10% (ingår i priset)", "Noga utvald")
    assert pricing.discount_limit is None


def test_discount_maximum_quantity_is_carried():
    pricing = parse_pricing(product("500 ml", price="59.58", promotions=["-10%"],
                                    discount={"undiscounted_gross_price": "66.20", "maximum_quantity": 2}))
    assert pricing.discount_limit == 2 and pricing.undiscounted_price == 66.20


def test_prismatch_and_unknown_are_informational():
    pricing = parse_pricing(product("5 dl", promotions=["Prismatch", "Köp 2 betala för 1"]))
    assert pricing.deals == () and pricing.informational == ("Prismatch", "Köp 2 betala för 1")
