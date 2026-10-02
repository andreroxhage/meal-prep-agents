import pytest

from mathem_cart.mathem.errors import MathemProtocolError
from mathem_cart.mathem.models import Product

# Trimmed from a live search response, 2026-09-24.
ARLA = {
    "id": 2380, "full_name": "Arla Köket® Vispgrädde 36%", "brand": "Arla Köket®",
    "name": "Vispgrädde 36%", "name_extra": "5 dl", "gross_price": "28.60",
    "gross_unit_price": "57.20", "unit_price_quantity_abbreviation": "l",
    "client_classifiers": [{"name": "Färskvarugaranti i 5 dagar"}, {"name": "FSC Forest Steward Council Mix"}],
    "currency": "SEK", "discount": None,
    "promotions": [{"title": "Prismatch", "display_style": "price_match"}],
    "availability": {"is_available": True, "code": "available"},
}

GLASS = {
    "id": 11067, "full_name": "Österhagen Glass Gräddglass Salt Gräddkola EKO/KRAV",
    "name_extra": "500 ml", "gross_price": "59.58", "gross_unit_price": "119.16",
    "unit_price_quantity_abbreviation": "l", "client_classifiers": [],
    "promotions": [{"title": "-10%"}, {"title": "Noga utvald"}],
    "discount": {"is_discounted": True, "undiscounted_gross_price": "66.20", "maximum_quantity": None},
    "availability": {"is_available": True, "code": "available"},
}


def test_from_api_snake_case():
    p = Product.from_api(ARLA)
    assert p.id == 2380
    assert p.full_name == "Arla Köket® Vispgrädde 36%"
    assert p.name_extra == "5 dl"
    assert p.gross_price == 28.60
    assert p.gross_unit_price == 57.20
    assert p.unit_price_unit == "l"
    assert p.classifiers == ("Färskvarugaranti i 5 dagar", "FSC Forest Steward Council Mix")
    assert p.promotions == ("Prismatch",)
    assert p.available is True
    assert p.availability_code == "available"
    assert p.previously_bought is False


def test_from_api_camel_case_is_equivalent():
    camel = {"id": 2380, "fullName": "Arla Köket® Vispgrädde 36%", "nameExtra": "5 dl",
             "grossPrice": "28.60", "grossUnitPrice": "57.20",
             "unitPriceQuantityAbbreviation": "l",
             "availability": {"isAvailable": True, "code": "available"}}
    p = Product.from_api(camel)
    assert (p.full_name, p.name_extra, p.gross_price, p.gross_unit_price, p.unit_price_unit, p.available) == (
        "Arla Köket® Vispgrädde 36%", "5 dl", 28.60, 57.20, "l", True)


def test_discount_block_is_normalised():
    p = Product.from_api(GLASS)
    assert p.promotions == ("-10%", "Noga utvald")
    assert p.discount == {"is_discounted": True, "undiscounted_gross_price": "66.20", "maximum_quantity": None}


def test_sold_out_and_missing_availability_are_unavailable():
    sold = Product.from_api({**ARLA, "availability": {"is_available": False, "code": "sold_out"}})
    assert (sold.available, sold.availability_code) == (False, "sold_out")
    missing = {k: v for k, v in ARLA.items() if k != "availability"}
    assert Product.from_api(missing).available is False


def test_null_price_is_none_not_zero():
    p = Product.from_api({**ARLA, "gross_price": None, "gross_unit_price": ""})
    assert p.gross_price is None and p.gross_unit_price is None


@pytest.mark.parametrize("field", ["id", "full_name"])
def test_missing_required_field_raises_protocol_error(field):
    data = {k: v for k, v in ARLA.items() if k != field}
    with pytest.raises(MathemProtocolError, match=field):
        Product.from_api(data)
