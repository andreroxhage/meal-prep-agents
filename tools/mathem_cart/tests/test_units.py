import math

import pytest

from mathem_cart.units import Amount, Conversions, convert, lookup, to_base

CONV = Conversions(piece_weight_g={"gul lök": 150, "citron": 120, "vitlöksklyfta": 5},
                   density_g_per_dl={"vetemjöl": 60, "jasminris": 85})


@pytest.mark.parametrize("value,unit,expected", [
    (1.2, "kg", Amount(1200, "g")), (500, "g", Amount(500, "g")),
    (3, "dl", Amount(300, "ml")), (2, "msk", Amount(30, "ml")), (1, "tsk", Amount(5, "ml")),
    (1, "krm", Amount(1, "ml")), (33, "cl", Amount(330, "ml")), (1.5, "l", Amount(1500, "ml")),
    (6, "st", Amount(6, "st")), (2, "förp", Amount(2, "förp")), (1, "knippe", Amount(1, "förp")),
])
def test_to_base(value, unit, expected):
    got = to_base(value, unit)
    assert got.dim == expected.dim and got.value == pytest.approx(expected.value)


def test_to_base_unknown_unit():
    assert to_base(1, "näve") is None


def test_lookup_whole_words_longest_first():
    assert lookup(CONV.piece_weight_g, "gul lök") == 150
    assert lookup(CONV.piece_weight_g, "citronsaft") is None
    assert lookup(CONV.piece_weight_g, "ekologisk citron") == 120
    assert lookup(CONV.piece_weight_g, "citronsaft") is None


def test_convert_same_dim_is_identity():
    assert convert(Amount(300, "ml"), "ml", "vispgrädde", CONV) == Amount(300, "ml")


def test_convert_pieces_to_grams_and_back():
    assert convert(Amount(3, "st"), "g", "gul lök", CONV) == Amount(450, "g")
    assert convert(Amount(600, "g"), "st", "gul lök", CONV) == Amount(4, "st")


def test_convert_volume_to_grams_via_density():
    got = convert(Amount(150, "ml"), "g", "jasminris", CONV)
    assert got.dim == "g" and got.value == pytest.approx(127.5)


def test_convert_without_path_is_none():
    assert convert(Amount(3, "st"), "g", "okänd grönsak", CONV) is None
    assert convert(Amount(2, "förp"), "g", "pasta", CONV) is None


@pytest.mark.parametrize("key,expected", [
    ("citroner", 120), ("vitlöksklyftor", 5), ("gula lökar", 150), ("ekologiska citroner", 120),
    ("citronerna", None), ("citronsaften", None),
])
def test_lookup_accepts_plural_list_keys(key, expected):
    # Q2: shopping lists say "3 st citroner"; the table says "citron".
    assert lookup(CONV.piece_weight_g, key) == expected


def test_convert_plural_pieces_to_grams():
    assert convert(Amount(3, "st"), "g", "vitlöksklyftor", CONV) == Amount(15, "g")


def test_pieces_of_different_things_are_not_counted_one_for_one():
    # Q1: 3 cloves are not 3 garlic heads. Without a piece weight for the product there is no path.
    assert convert(Amount(3, "st"), "st", "vitlöksklyftor", CONV, product="Garant Vitlök") is None
    with_head = Conversions(piece_weight_g={**CONV.piece_weight_g, "vitlök": 50})
    got = convert(Amount(3, "st"), "st", "vitlöksklyftor", with_head, product="Garant Vitlök")
    assert got.dim == "st" and got.value == pytest.approx(0.3)


def test_pieces_of_the_same_thing_still_count_one_for_one():
    assert convert(Amount(3, "st"), "st", "citroner", CONV, product="Citron Eko") == Amount(3, "st")
    assert convert(Amount(6, "st"), "st", "ägg", CONV, product="Ägg 12-pack") == Amount(6, "st")


@pytest.mark.parametrize("key,product", [
    ("citroner", "Citroner 4-pack"), ("gul lök", "Lök Gul Klass 1"), ("vitlöksklyftor", "Vitlöksklyftor skalade"),
])
def test_product_names_in_other_word_order_or_plural_still_count_one_for_one(key, product):
    assert convert(Amount(3, "st"), "st", key, CONV, product=product) == Amount(3, "st")


@pytest.mark.parametrize("unit", ["kruka", "flaska", "limpa", "påse"])
def test_package_words_are_package_counts(unit):
    assert to_base(2, unit) == Amount(2, "förp")


PRODUCE = Conversions(piece_weight_g={"gurka": 300, "avokado": 200, "lime": 70, "rödlök": 120, "citron": 120},
                      density_g_per_dl={})


@pytest.mark.parametrize("key,need,package,count", [
    ("gurka", 2, 270, 2),       # "Gurka Svensk, 270 g" is one cucumber, not 0,9
    ("avokado", 6, 167, 6),
    ("avokado", 6, 325, 3),     # 2-pack
    ("lime", 4, 200, 2),        # 3-pack: 2 packs, not 2 packs of 200 g read as grams
    ("rödlök", 5, 90, 5),       # styck 90 g: used to buy 7 for 5
    ("citron", 3, 500, 1),      # a net of about four
])
def test_a_package_counts_as_its_weight_in_whole_pieces(key, need, package, count):
    grams = convert(Amount(need, "st"), "g", key, PRODUCE, package=Amount(package, "g"))
    assert math.ceil(grams.value / package - 1e-9) == count


def test_without_a_package_pieces_convert_through_the_table_weight():
    assert convert(Amount(2, "st"), "g", "gurka", PRODUCE) == Amount(600, "g")


def test_umlaut_plurals_find_their_singular():
    conv = Conversions(piece_weight_g={"morot": 100}, density_g_per_dl={})
    assert lookup(conv.piece_weight_g, "morötter") == 100
