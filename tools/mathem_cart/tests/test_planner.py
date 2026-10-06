import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mathem_cart.mathem.models import Product
from mathem_cart.mathem.products import parse_search
from mathem_cart.pins import load_pins
from mathem_cart.planner import Answer, Planner, PlannerDeps, agent_order, need_for, settle_all
from mathem_cart.plan_model import PlanLine
from mathem_cart.rules import filter_candidates, load_rules, parse_rules
from mathem_cart.shopping_list import Item, parse_shopping_list
from mathem_cart.units import Amount, Conversions

FIX = Path(__file__).parent / "fixtures"
# The committed rule file, unpatched: what ships is what gets tested (F1).
RULES = load_rules(Path(__file__).parents[1] / "mathem-regler.yaml")
NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone(timedelta(hours=2)))


def fixture(name):
    return parse_search(json.loads((FIX / name).read_text(encoding="utf-8")))[0]


VISP = fixture("search-vispgradde.json")
KYCK = fixture("search-kycklingfile.json")
LIST = parse_shopping_list("## Mejeri & Ägg\n- 3 dl vispgrädde\n## Kött & Fisk\n- 1,2 kg kycklingfilé\n"
                           "## Skafferi-antaganden\n- Salt\n")


def search(term):
    return {"vispgrädde": VISP, "kycklingfilé": KYCK}.get(term, [])


def deps(tmp_path, **kw):
    base = dict(search=search, lookup=lambda pid: None, rules=RULES, pins=load_pins(tmp_path / "pins.yaml"))
    base.update(kw)
    return PlannerDeps(**base)


def settle(tmp_path, shopping=LIST, skip=(), **kw):
    planner = Planner(deps(tmp_path, **kw))
    return planner, settle_all(shopping, planner, skip)


def finished(planner, settled, shopping=LIST):
    return planner.finish(week="w", now=NOW, outcomes=[settled.decided[v] for v in settled.order],
                          skipped=settled.skipped, excluded=shopping.excluded)


def cheapest_available(products):
    return min((p for p in products if p.available and p.gross_price), key=lambda p: p.gross_price)


def kept(products, category):
    return [p.id for p in filter_candidates(products, RULES.for_category(category))[0]]


def test_unpinned_items_are_pending_with_rule_filtered_candidates_in_agent_order(tmp_path):
    _, s = settle(tmp_path)
    assert s.decided == {} and s.order == ["v01", "v02"]
    assert [(p.vara_id, p.term, p.item.name) for p in s.pending] == [("v01", "vispgrädde", "vispgrädde"),
                                                                      ("v02", "kycklingfilé", "kycklingfilé")]
    rule_kept = filter_candidates(VISP, RULES.for_category("Mejeri & Ägg"))[0]
    assert [p.id for p in s.pending[0].products] == [p.id for p in agent_order(rule_kept)]
    assert [p.id for p in s.pending[0].products][:15] == kept(VISP, "Mejeri & Ägg")[:15]
    # kycklingfilé is in tillåt_fryst: frozen fillets stay, the rest of the rules still apply
    assert any("fryst" in p.full_name.casefold() for p in s.pending[1].products)
    assert all("marinerad" not in p.full_name.casefold() for p in s.pending[1].products)


def test_no_survivors_is_still_pending_with_no_candidates(tmp_path):
    rules = parse_rules({"kategorier": {"Kött & Fisk": {"kräv_någon_av": ["namn:finns-inte"]}}})
    _, s = settle(tmp_path, rules=rules)
    assert s.pending[1].vara_id == "v02" and s.pending[1].products == []


def test_skipped_items_keep_the_other_ids_stable(tmp_path):
    _, s = settle(tmp_path, skip=["Vispgrädde"])
    assert s.skipped == ["vispgrädde"] and s.order == ["v02"] and s.pending[0].vara_id == "v02"


def test_missing_amount_is_undecided_without_matching(tmp_path):
    shopping = parse_shopping_list("## Mejeri & Ägg\n- vispgrädde efter smak\n")
    _, s = settle(tmp_path, shopping)
    assert s.pending == [] and s.decided["v01"].reason == "mängd saknas"


def test_pins_pick_cheapest_approved_and_compute_quantity(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    a, b = [p for p in VISP if p.available and p.gross_price][:2]
    pins.approve("vispgrädde", a.id)
    pins.approve("vispgrädde", b.id)
    planner, s = settle(tmp_path, pins=pins)
    line = s.decided["v01"]
    assert isinstance(line, PlanLine) and line.decision == "pin" and line.reason is None
    assert line.product_id in {a.id, b.id} and line.count >= 1 and line.cost_kr > 0
    assert [p.vara_id for p in s.pending] == ["v02"]


def test_fixed_pin_outside_results_uses_lookup(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    pins.set_fixed("vispgrädde", 999999)
    extra = Product.from_api({"id": 999999, "full_name": "Specialgrädde", "name_extra": "5 dl",
                              "gross_price": "30.00", "availability": {"is_available": True, "code": "available"}})
    _, s = settle(tmp_path, pins=pins, lookup=lambda pid: extra if pid == 999999 else None)
    assert s.decided["v01"].product_id == 999999 and s.decided["v01"].decision == "fast"


def test_fixed_pin_unavailable_is_undecided_not_swapped(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    pins.set_fixed("vispgrädde", 999999)
    _, s = settle(tmp_path, pins=pins)
    assert s.decided["v01"].reason == "fast produkt ej tillgänglig"


def test_pinned_search_term_is_the_pending_term(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    pins.set_search("grädde", "vispgrädde")
    _, s = settle(tmp_path, parse_shopping_list("## Mejeri & Ägg\n- 3 dl grädde\n"), pins=pins)
    assert s.pending[0].term == "vispgrädde" and s.pending[0].products


def test_line_for_carries_the_model_decision_and_reason(tmp_path):
    planner = Planner(deps(tmp_path))
    item = LIST.items[0]
    line = planner.line_for(item, [cheapest_available(VISP)], "haiku", "vanlig vispgrädde")
    assert line.decision == "haiku" and line.reason == "vanlig vispgrädde"
    assert planner.offers[line.product_id].product_id == line.product_id


def test_undecided_for_shows_five_candidates_in_given_order_and_the_note(tmp_path):
    planner = Planner(deps(tmp_path))
    u = planner.undecided_for(LIST.items[0], "osäker", VISP, "fetthalt oklar")
    assert [c.product_id for c in u.candidates] == [p.id for p in VISP[:5]]
    assert u.note == "fetthalt oklar" and u.need.unit == "ml"


def test_candidates_for_applies_the_category_rules(tmp_path):
    planner = Planner(deps(tmp_path))
    rule = RULES.rule_for("kycklingfilé", "Kött & Fisk")
    expected = [p.id for p in agent_order(filter_candidates(KYCK, rule)[0])]
    assert [p.id for p in planner.candidates_for(LIST.items[1], "kycklingfilé")] == expected


class ScriptedAsker:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def ask(self, item, candidates):
        self.asked.append(item.key)
        return self.answers.pop(0)


def test_ask_accept_saves_pin_and_decides(tmp_path):
    pick = cheapest_available(VISP)
    planner, s = settle(tmp_path)
    first = planner.undecided_for(LIST.items[0], "matchning saknas", s.pending[0].products)
    line = planner.ask(LIST.items[0], "v01", first, ScriptedAsker([Answer("accept", pick.id)]))
    assert line.product_id == pick.id and line.decision == "pin"
    assert load_pins(tmp_path / "pins.yaml").get("vispgrädde").approved == [pick.id]


def test_ask_skip_returns_none(tmp_path):
    planner = Planner(deps(tmp_path))
    first = planner.undecided_for(LIST.items[0], "osäker", VISP)
    assert planner.ask(LIST.items[0], "v01", first, ScriptedAsker([Answer("skip")])) is None


def test_ask_new_search_term_is_saved_and_searched(tmp_path):
    seen = []
    planner = Planner(deps(tmp_path, search=lambda t: seen.append(t) or search(t)))
    item = parse_shopping_list("## Mejeri & Ägg\n- 3 dl grädde\n").items[0]
    first = planner.undecided_for(item, "ingen passar", [])
    result = planner.ask(item, "v01", first, ScriptedAsker([Answer("search", term="vispgrädde"), Answer("skip")]))
    assert result is None and seen == ["vispgrädde"]
    assert load_pins(tmp_path / "pins.yaml").get("grädde").search == "vispgrädde"


def test_ask_gives_up_after_five_rounds(tmp_path):
    asker = ScriptedAsker([Answer("search", term=f"x{i}") for i in range(10)])
    planner = Planner(deps(tmp_path))
    item = parse_shopping_list("## Mejeri & Ägg\n- 3 dl grädde\n").items[0]
    result = planner.ask(item, "v01", planner.undecided_for(item, "ingen passar", []), asker)
    assert len(asker.asked) == 5 and result.reason == "inga kandidater"


def test_spoon_measure_spice_is_one_package():
    assert need_for(Item("dijonsenap", "dijonsenap", 2, "msk", "Kryddor & Såser")) == Amount(1, "förp")
    assert need_for(Item("olivolja", "olivolja", 3, "msk", "Skafferi")) == Amount(45, "ml")


def test_null_price_product_is_undecided_not_crash(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    broken = Product.from_api({"id": 5, "full_name": "Trasig", "name_extra": "5 dl", "gross_price": None,
                               "availability": {"is_available": True, "code": "available"}})
    pins.set_fixed("vispgrädde", 5)
    _, s = settle(tmp_path, pins=pins, lookup=lambda pid: broken)
    assert s.decided["v01"].reason == "ingen förpackning går att räkna"


def _jar(pid, name, extra, price):
    return Product.from_api({"id": pid, "full_name": name, "name_extra": extra, "gross_price": str(price),
                             "availability": {"is_available": True, "code": "available"}})


def test_spoon_measure_without_conversion_path_is_one_package_in_any_category(tmp_path):
    jars = {1: _jar(1, "Mutti Tomatpuré", "200 g", 22), 2: _jar(2, "Garant Honung", "500 g", 45),
            3: _jar(3, "Sambal Oelek", "200 g", 30), 4: _jar(4, "Olivolja", "500 ml", 80)}
    pins = load_pins(tmp_path / "pins.yaml")
    for key, pid in (("tomatpuré", 1), ("honung", 2), ("sambal oelek", 3), ("olivolja", 4)):
        pins.approve(key, pid)
    shopping = parse_shopping_list("## Skafferi\n- 2 msk tomatpuré\n- 1 msk honung\n- 2 tsk sambal oelek\n"
                                   "- 3 msk olivolja\n")
    planner, s = settle(tmp_path, shopping, pins=pins, lookup=jars.get)
    plan = finished(planner, s, shopping)
    assert plan.undecided == []
    assert [(l.item, l.count, l.cost_kr) for l in plan.lines] == [
        ("tomatpuré", 1, 22.0), ("honung", 1, 45.0), ("sambal oelek", 1, 30.0), ("olivolja", 1, 80.0)]
    assert plan.lines[3].need.unit == "ml" and plan.lines[3].overshoot > 0


def _garlic(tmp_path, rules):
    head = Product.from_api({"id": 7, "full_name": "Vitlök", "name_extra": "1 st", "gross_price": "6",
                             "gross_unit_price": "6", "unit_price_quantity_abbreviation": "st",
                             "availability": {"is_available": True, "code": "available"}})
    pins = load_pins(tmp_path / "pins.yaml")
    pins.set_fixed("vitlöksklyftor", 7)
    shopping = parse_shopping_list("## Grönsaker\n- 2–3 st vitlöksklyftor\n")
    planner, s = settle(tmp_path, shopping, pins=pins, rules=rules, lookup=lambda pid: head)
    return finished(planner, s, shopping)


def test_cloves_are_not_bought_as_whole_heads_without_a_head_weight(tmp_path):
    weights = {k: v for k, v in RULES.conversions.piece_weight_g.items() if k != "vitlök"}
    rules = replace(RULES, conversions=Conversions(piece_weight_g=weights,
                                                   density_g_per_dl=RULES.conversions.density_g_per_dl))
    plan = _garlic(tmp_path, rules)
    assert plan.lines == [] and plan.undecided[0].reason == "ingen förpackning går att räkna"


def test_cloves_convert_to_heads_through_the_committed_head_weight(tmp_path):
    # Q1: 3 cloves used to buy 3 heads; with vitlök: 50 g in the rules it is one head.
    line = _garlic(tmp_path, RULES).lines[0]
    assert line.count == 1 and line.overshoot > 0


def test_plural_list_key_uses_singular_piece_weight(tmp_path):
    net = Product.from_api({"id": 8, "full_name": "Citron", "name_extra": "ca 500 g", "gross_price": "25",
                            "gross_unit_price": "50", "unit_price_quantity_abbreviation": "kg",
                            "availability": {"is_available": True, "code": "available"}})
    pins = load_pins(tmp_path / "pins.yaml")
    pins.set_fixed("citroner", 8)
    shopping = parse_shopping_list("## Frukt\n- 3 st citroner\n")
    planner, s = settle(tmp_path, shopping, pins=pins, lookup=lambda pid: net)
    assert [(l.item, l.count, l.cost_kr) for l in finished(planner, s, shopping).lines] == [("citroner", 1, 25.0)]


def _shared(tmp_path, product, keys, text):
    pins = load_pins(tmp_path / "pins.yaml")
    for key in keys:
        pins.set_fixed(key, product.id)
    shopping = parse_shopping_list(text)
    planner, s = settle(tmp_path, shopping, pins=pins, lookup=lambda pid: product)
    return finished(planner, s, shopping)


def test_max_per_customer_is_enforced_across_lines(tmp_path):
    kronfagel = Product.from_api({
        "id": 66316, "full_name": "Kronfågel Kycklinglårfilé", "name_extra": "Max 2 per kund, 700 g",
        "gross_price": "72.50", "promotions": [{"title": "2 för 99 kr"}],
        "discount": {"maximum_quantity": 2, "undiscounted_gross_price": "72.50"},
        "client_classifiers": [{"name": "Svensk Fågel"}],
        "availability": {"is_available": True, "code": "available"}})
    plan = _shared(tmp_path, kronfagel, ("kycklinglårfilé", "kycklingfilé"),
                   "## Kött & Fisk\n- 1,4 kg kycklinglårfilé\n- 700 g kycklingfilé\n")
    assert [(l.item, l.count) for l in plan.lines] == [("kycklinglårfilé", 2)]
    assert [(u.item, u.reason) for u in plan.undecided] == [
        ("kycklingfilé", "max antal per kund räcker inte (delas med kycklinglårfilé)")]
    assert plan.total_kr == pytest.approx(99.0)


def test_discount_limit_is_priced_across_lines(tmp_path):
    cream = Product.from_api({
        "id": 9, "full_name": "Grädde", "name_extra": "5 dl", "gross_price": "59.58",
        "promotions": [{"title": "-10%"}],
        "discount": {"maximum_quantity": 2, "undiscounted_gross_price": "66.20"},
        "availability": {"is_available": True, "code": "available"}})
    plan = _shared(tmp_path, cream, ("vispgrädde", "matlagningsgrädde"),
                   "## Mejeri & Ägg\n- 1 l vispgrädde\n- 1 l matlagningsgrädde\n")
    assert [(l.count, l.cost_kr) for l in plan.lines] == [(2, 119.16), (2, 132.4)]
    assert plan.total_kr == pytest.approx(251.56)


def _salmon(pid, classifiers=()):
    return Product.from_api({"id": pid, "full_name": f"Laxfilé {pid}", "name_extra": "500 g", "gross_price": "99.00",
                             "client_classifiers": [{"name": c} for c in classifiers],
                             "availability": {"is_available": True, "code": "available"}})


PREFER_RULES = parse_rules({"kategorier": {"Kött & Fisk": {"frysbar": "ja",
                                                           "föredra_någon_av": ["märkning:Från Sverige"]}}})
SALMON = parse_shopping_list("## Kött & Fisk\n- 1 kg laxfilé\n").items[0]


def test_model_pick_of_a_non_preferred_product_is_flagged(tmp_path):
    planner = Planner(deps(tmp_path, rules=PREFER_RULES))
    line = planner.line_for(SALMON, [_salmon(77, ("Från Norge",))], "haiku", "laxfilé")
    assert "ej föredragen" in line.flags


def test_preferred_product_is_the_only_candidate_when_present(tmp_path):
    imported, swedish = _salmon(77, ("Från Norge",)), _salmon(78, ("Från Sverige",))
    planner = Planner(deps(tmp_path, rules=PREFER_RULES, search=lambda t: [imported, swedish]))
    assert [p.id for p in planner.candidates_for(SALMON, "laxfilé")] == [78]
    assert "ej föredragen" not in planner.line_for(SALMON, [swedish], "haiku").flags


def test_pinned_non_preferred_product_is_the_users_choice_and_not_flagged(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    pins.approve("laxfilé", 77)
    shopping = parse_shopping_list("## Kött & Fisk\n- 1 kg laxfilé\n")
    _, s = settle(tmp_path, shopping, pins=pins, rules=PREFER_RULES, search=lambda t: [_salmon(77, ("Från Norge",))])
    assert s.decided["v01"].product_id == 77 and "ej föredragen" not in s.decided["v01"].flags


def test_finish_keeps_list_order_and_totals(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    pins.approve("vispgrädde", cheapest_available(VISP).id)
    planner, s = settle(tmp_path, pins=pins)
    outcomes = [s.decided["v01"], planner.undecided_for(LIST.items[1], "osäker", s.pending[0].products)]
    plan = planner.finish(week="w", now=NOW, outcomes=outcomes, skipped=[], excluded=LIST.excluded)
    assert [l.item for l in plan.lines] == ["vispgrädde"] and [u.item for u in plan.undecided] == ["kycklingfilé"]
    assert plan.total_kr == pytest.approx(plan.lines[0].cost_kr) and plan.excluded == ["Salt"]


def test_alcohol_is_listed_as_bought_at_systembolaget_and_keeps_ids_stable(tmp_path):
    shopping = parse_shopping_list("## Övrigt\n- 1 dl torrt vitt vin\n- 1 burk ljus lager\n## Mejeri & Ägg\n- 3 dl vispgrädde\n")
    _, s = settle(tmp_path, shopping)
    assert s.excluded == ["torrt vitt vin (köps på Systembolaget)", "ljus lager (köps på Systembolaget)"]
    assert s.order == ["v03"] and [p.vara_id for p in s.pending] == ["v03"]


def test_produce_counted_in_pieces_buys_whole_pieces(tmp_path):
    cucumber = Product.from_api({"id": 4672, "full_name": "Gurka Svensk Klass1 Sverige",
                                 "name_extra": "Max 10 per kund, Sverige, 270 g", "gross_price": "16.95",
                                 "gross_unit_price": "62.78", "unit_price_quantity_abbreviation": "kg",
                                 "availability": {"is_available": True, "code": "available"}})
    planner = Planner(deps(tmp_path))
    item = parse_shopping_list("## Grönsaker\n- 2 st gurka\n").items[0]
    line = planner.line_for(item, [cucumber], "haiku")
    assert (line.count, line.cost_kr) == (2, 33.9)


def _priced(pid, unit_price, unit="kg"):
    return Product.from_api({"id": pid, "full_name": f"P{pid}", "name_extra": "1 kg", "gross_price": "10",
                             "gross_unit_price": str(unit_price), "unit_price_quantity_abbreviation": unit,
                             "availability": {"is_available": True}})


def test_agent_order_moves_the_cheapest_per_kg_up_behind_the_first_fifteen():
    products = [_priced(i, 100) for i in range(1, 16)] + [_priced(16, 90), _priced(17, 40, "st"),
                                                          _priced(18, 50), _priced(19, 95)]
    order = [p.id for p in agent_order(products, extra=2)]
    assert order[:15] == list(range(1, 16))
    assert order[15:17] == [18, 16]                   # kr/kg only, cheapest first; kr/st is skipped
    assert sorted(order) == list(range(1, 20))        # nothing lost


def test_storpack_line_picks_the_big_pack_and_fresh_items_keep_lowest_cost(tmp_path):
    def p(pid, extra, price, unit_price, unit="kg"):
        return Product.from_api({"id": pid, "full_name": f"Vara {pid}", "name_extra": extra,
                                 "gross_price": str(price), "gross_unit_price": str(unit_price),
                                 "unit_price_quantity_abbreviation": unit, "availability": {"is_available": True}})
    planner = Planner(deps(tmp_path))
    chicken = Item(name="kycklingfilé", key="kycklingfilé", amount=1.5, unit="kg", category="Kött & Fisk")
    line = planner.line_for(chicken, [p(1, "900 g", 119, 132.2), p(2, "2,5 kg", 249, 99.6)], "haiku")
    assert (line.product_id, line.count, "storpack" in line.flags) == (2, 1, True)
    cream = Item(name="vispgrädde", key="vispgrädde", amount=6, unit="dl", category="Mejeri & Ägg")
    line = planner.line_for(cream, [p(3, "3 dl", 22, 73.3, "l"), p(4, "1 l", 49, 49, "l")], "haiku")
    assert (line.product_id, line.count) == (3, 2)


def test_basvara_line_buys_the_potato_sack_within_its_max_amount(tmp_path):
    def p(pid, extra, price, unit_price):
        return Product.from_api({"id": pid, "full_name": f"Potatis {pid}", "name_extra": extra,
                                 "gross_price": str(price), "gross_unit_price": str(unit_price),
                                 "unit_price_quantity_abbreviation": "kg", "availability": {"is_available": True}})
    planner = Planner(deps(tmp_path))
    potatoes = Item(name="fast potatis", key="fast potatis", amount=800, unit="g", category="Grönsaker")
    offers = [p(1, "1 kg", 20, 20), p(2, "5 kg", 59, 11.8), p(3, "10 kg", 99, 9.9)]
    line = planner.line_for(potatoes, offers, "haiku")
    assert (line.product_id, line.count, "storpack" in line.flags) == (2, 1, True)   # 10 kg is over 5 kg


def test_frozen_chicken_reaches_the_agents_when_tillat_fryst_lists_it(tmp_path):
    frozen = Product.from_api({"id": 900, "full_name": "Garant Kyckling Bröstfilé Fryst", "name_extra": "1000 g",
                               "gross_price": "91.50", "availability": {"is_available": True},
                               "client_classifiers": [{"name": "Från Sverige"}]})
    planner = Planner(deps(tmp_path, search=lambda term: [frozen]))
    chicken = Item(name="kycklingfilé", key="kycklingfilé", amount=1, unit="kg", category="Kött & Fisk")
    beef = Item(name="högrev", key="högrev", amount=1, unit="kg", category="Kött & Fisk")
    assert [p.id for p in planner.candidates_for(chicken, "kycklingfilé")] == [900]
    assert planner.candidates_for(beef, "högrev") == []
