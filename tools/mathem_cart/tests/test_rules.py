from pathlib import Path

import pytest

from mathem_cart.mathem.models import Product
from mathem_cart.rules import CategoryRule, RulesError, filter_candidates, load_rules, meets_preference, parse_rules
from mathem_cart.units import Amount

REPO_RULES = Path(__file__).parents[1] / "mathem-regler.yaml"


def product(pid, name, extra="700 g", classifiers=(), available=True):
    return Product.from_api({"id": pid, "full_name": name, "name_extra": extra, "gross_price": "10",
                             "client_classifiers": [{"name": c} for c in classifiers],
                             "availability": {"is_available": available, "code": "available" if available else "sold_out"}})


def test_committed_rule_file_loads():
    rules = load_rules(REPO_RULES)
    assert rules.max_count_per_line == 10 and rules.plan_max_age_h == 24
    meat = rules.for_category("Kött & Fisk")
    assert meat.frysbar is True and meat.overshoot_cap() is None
    assert "fryst" in meat.exclude and "märkning:Från Sverige" in meat.prefer_any
    assert rules.for_category("grönsaker").overshoot_cap() == 0.25     # case-insensitive
    assert rules.for_category("Bröd").overshoot_cap() == 0.25          # default
    assert rules.conversions.piece_weight_g["gul lök"] == 175


def test_ja_nej_and_booleans():
    rules = parse_rules({"kategorier": {"A": {"frysbar": "ja"}, "B": {"frysbar": "nej"}, "C": {"frysbar": True}}})
    assert [rules.for_category(c).frysbar for c in "ABC"] == [True, False, True]


def test_category_overshoot_override():
    rules = parse_rules({"standard": {"max_överköp": 0.3}, "kategorier": {"Frukt": {"max_överköp": 0.5}}})
    assert rules.for_category("Frukt").overshoot_cap() == 0.5
    assert rules.for_category("Bröd").overshoot_cap() == 0.3


@pytest.mark.parametrize("bad", [
    {"kategorier": {"A": {"kräv_någon_av": ["färg:röd"]}}},
])
def test_invalid_rules_raise(bad):
    with pytest.raises(RulesError):
        parse_rules(bad)


def test_old_matching_keys_load_with_one_warning():
    rules = parse_rules({"matchning": {"läge": "yolo", "tröskel": 1.5}})
    assert len(rules.warnings) == 1
    assert "matchning" in rules.warnings[0] and "Laya" in rules.warnings[0]
    assert parse_rules({}).warnings == ()


def test_committed_rules_have_no_matching_block():
    rules = load_rules(Path(__file__).parents[1] / "mathem-regler.yaml")
    assert rules.warnings == ()
    assert not hasattr(rules, "mode") and not hasattr(rules, "threshold")


def test_exclude_matches_full_name_and_name_extra_case_insensitive():
    rule = CategoryRule(exclude=("fryst", "marinerad"))
    keep = product(1, "Kronfågel Kycklingfilé")
    frozen = product(2, "Garant Innerfilé av Svensk Kyckling Fryst")
    marinated = product(3, "Kycklingfilé", extra="MARINERAD, 500 g")
    kept, dropped = filter_candidates([keep, frozen, marinated], rule)
    assert kept == [keep]
    assert [(p.id, reason) for p, reason in dropped] == [(2, "utesluten: fryst"), (3, "utesluten: marinerad")]


def test_require_any_label_or_name():
    rule = CategoryRule(require_any=("märkning:Från Sverige", "namn:svensk"))
    label = product(1, "Kronfågel Kycklingfilé", classifiers=("Från Sverige",))
    name = product(2, "Svensk Kycklingbröstfilé")
    neither = product(3, "Kycklingfilé Brasilien", classifiers=("Lactose free",))
    kept, dropped = filter_candidates([label, name, neither], rule)
    assert kept == [label, name]
    assert dropped[0][1] == "uppfyller inget krav: märkning:Från Sverige, namn:svensk"


def test_unavailable_is_dropped():
    kept, dropped = filter_candidates([product(1, "Mjölk", available=False)], CategoryRule())
    assert kept == [] and dropped[0][1] == "ej tillgänglig"


def test_committed_meat_rule_keeps_fresh_swedish_chicken():
    # F1: Mathem labels Swedish meat "Svensk Fågel" / "Kött från Sverige", never "Från Sverige".
    import json
    from mathem_cart.mathem.products import parse_search
    fixture = Path(__file__).parent / "fixtures" / "search-kycklingfile.json"
    products = parse_search(json.loads(fixture.read_text(encoding="utf-8")))[0]
    kept, _ = filter_candidates(products, load_rules(REPO_RULES).for_category("Kött & Fisk"))
    names = [p.full_name for p in kept]
    assert any("Guldfågeln" in n for n in names) and any("Kronfågel" in n for n in names)
    assert all("fryst" not in f"{p.full_name} {p.name_extra}".casefold() for p in kept)


@pytest.mark.parametrize("label", ["Svensk Fågel", "Kött från Sverige", "Svenskt Kött"])
def test_committed_meat_rule_accepts_mathem_swedish_labels(label):
    rule = load_rules(REPO_RULES).for_category("Kött & Fisk")
    kept, _ = filter_candidates([product(1, "Kycklingfilé", classifiers=(label,))], rule)
    assert [p.id for p in kept] == [1]


def test_prefer_keeps_only_preferred_when_any_exist():
    rule = CategoryRule(prefer_any=("märkning:Från Sverige",))
    swedish = product(1, "Kycklingfilé", classifiers=("Från Sverige",))
    imported = product(2, "Kycklingfilé Brasilien")
    kept, dropped = filter_candidates([imported, swedish], rule)
    assert kept == [swedish]
    assert dropped == [(imported, "föredraget alternativ finns: märkning:Från Sverige")]


def test_prefer_falls_back_to_all_when_nothing_is_preferred():
    # Not Swedish is fine when nothing Swedish is available (user, 2026-09-24).
    rule = CategoryRule(prefer_any=("märkning:Från Sverige", "namn:svensk"))
    norway, faroe = product(1, "Laxfilé Norge"), product(2, "Laxfilé Färöarna")
    kept, dropped = filter_candidates([norway, faroe], rule)
    assert kept == [norway, faroe] and dropped == []


def test_prefer_is_applied_after_exclude_and_availability():
    rule = CategoryRule(prefer_any=("namn:svensk",), exclude=("fryst",))
    frozen_swedish = product(1, "Svensk Kyckling Fryst")
    sold_out_swedish = product(2, "Svensk Kycklingfilé", available=False)
    danish = product(3, "Kycklingfilé Danmark")
    kept, _ = filter_candidates([frozen_swedish, sold_out_swedish, danish], rule)
    assert kept == [danish]


def test_meets_preference():
    rule = CategoryRule(prefer_any=("märkning:Svensk Fågel",))
    assert meets_preference(product(1, "Kyckling", classifiers=("Svensk Fågel",)), rule)
    assert not meets_preference(product(2, "Kyckling"), rule)
    assert meets_preference(product(2, "Kyckling"), CategoryRule())


def test_prefer_is_parsed_and_validated():
    rules = parse_rules({"kategorier": {"A": {"föredra_någon_av": ["märkning:Från Sverige"]}}})
    assert rules.for_category("A").prefer_any == ("märkning:Från Sverige",)
    with pytest.raises(RulesError):
        parse_rules({"kategorier": {"A": {"föredra_någon_av": ["färg:röd"]}}})


def test_committed_meat_rule_prefers_swedish_but_allows_imported_salmon():
    rule = load_rules(REPO_RULES).for_category("Kött & Fisk")
    assert rule.require_any == () and "märkning:Svensk Fågel" in rule.prefer_any
    salmon = product(1, "Laxfilé", classifiers=("Från Norge",))
    assert filter_candidates([salmon], rule)[0] == [salmon]


def test_items_bought_elsewhere_match_whole_words():
    rules = parse_rules({"köps_inte_på_mathem": {"Systembolaget": ["vin", "öl", "lager"]}})
    assert rules.bought_elsewhere("Torrt vitt vin") == "Systembolaget"
    assert rules.bought_elsewhere("Ljus lager") == "Systembolaget"
    assert rules.bought_elsewhere("Mörk ÖL") == "Systembolaget"
    for name in ("Risvinäger", "Rödvinsvinäger", "Matlagningsvin", "Lagerblad", "Mirin"):
        assert rules.bought_elsewhere(name) is None, name


@pytest.mark.parametrize("name,place", [
    ("Torrt vitt vin", "Systembolaget"), ("Vin, torrt vitt", "Systembolaget"), ("Ljus lager", "Systembolaget"),
    # Code review 2026-09-30: only the head noun counts, so vinegar and mustard stay on Mathem.
    ("Sherry vinäger", None), ("Vinäger, sherry", None), ("Cider-vinäger", None), ("Ale-senap", None),
])
def test_only_the_head_noun_sends_an_item_elsewhere(name, place):
    rules = parse_rules({"köps_inte_på_mathem": {"Systembolaget": ["vin", "lager", "sherry", "cider", "ale"]}})
    assert rules.bought_elsewhere(name) == place


def test_committed_rules_send_alcohol_to_systembolaget():
    rules = load_rules(REPO_RULES)
    assert rules.bought_elsewhere("Torrt vitt vin") == "Systembolaget"
    assert rules.bought_elsewhere("Ljus lager") == "Systembolaget"
    assert rules.bought_elsewhere("Rödvinsvinäger") is None


def test_committed_rules_have_piece_weights_for_produce_sold_by_the_piece():
    weights = load_rules(REPO_RULES).conversions.piece_weight_g
    for key in ("vitlök", "ingefära", "jalapeño", "gurka", "isbergssallad", "morot", "schalottenlök",
                "avokado", "lime", "päron"):
        assert weights.get(key), key


def test_bought_elsewhere_must_be_a_mapping_of_lists():
    with pytest.raises(RulesError):
        parse_rules({"köps_inte_på_mathem": ["vin"]})


def test_misspelt_safety_limit_fails_instead_of_default(tmp_path):
    path = tmp_path / "regler.yaml"
    path.write_text("säkerhet:\n  max_antal_rad: 5\n  plan_max_ålder_h: 24\n", encoding="utf-8")
    with pytest.raises(RulesError, match="max_antal_per_rad"):
        load_rules(path)


def test_storpack_categories_words_and_limits():
    rules = load_rules(REPO_RULES)
    assert rules.for_category("Kött & Fisk").storpack and not rules.for_category("Mejeri & Ägg").storpack
    assert rules.stock_up_for("kycklingfilé", "Kött & Fisk") == rules.stock_up
    assert rules.stock_up_for("osaltat smör", "Mejeri & Ägg") == rules.stock_up
    assert rules.stock_up_for("smör, osaltat", "Mejeri & Ägg") == rules.stock_up
    assert rules.stock_up_for("vispgrädde", "Mejeri & Ägg") is None
    assert (rules.stock_up.max_extra_share, rules.stock_up.max_extra_kr) == (0.5, 100)


def test_basvaror_bulk_staples_before_storpack():
    rules = load_rules(REPO_RULES)
    potatoes = rules.stock_up_for("fast potatis", "Grönsaker")
    assert potatoes.max_extra_share is None and potatoes.max_amount == Amount(5000, "g")
    rice = rules.stock_up_for("jasminris", "Skafferi")
    assert rice.max_amount is None and rice.allowance(20) == rice.max_extra_kr
    assert rules.stock_up_for("kapris", "Skafferi") == rules.stock_up          # not "ris"
    assert rules.stock_up_for("färskpotatis", "Grönsaker") is None              # doesn't keep
    assert rules.stock_up_for("färsk potatis", "Grönsaker") is None             # nor do these
    assert rules.stock_up_for("potatis, färsk", "Grönsaker") is None
    assert rules.stock_up_for("färsk pasta", "Mejeri & Ägg") is None
    assert rules.stock_up_for("picklad rödlök", "Skafferi") == rules.stock_up  # category storpack, not basvara
    assert rules.stock_up_for("röd lök", "Grönsaker") == rules.stock_up_for("rödlök", "Grönsaker")
    assert rules.stock_up_for("kokosmjölk", "Skafferi") == rules.stock_up      # cartons: storpack's share
    assert potatoes.max_multiple == 20


def test_basvaror_accepts_a_list_and_rejects_bad_amounts():
    rules = parse_rules({"basvaror": {"max_merkostnad_kr": 80, "varor": ["ris", "Pasta"]}})
    assert set(rules.staples) == {"ris", "pasta"} and rules.staples["ris"].max_extra_kr == 80
    rules = parse_rules({"basvaror": {"varor": {"potatis": "2,5 kg", "ris": "ja", "lök": True}}})
    assert rules.staples["potatis"].max_amount == Amount(2500, "g")
    assert rules.staples["ris"].max_amount is None and rules.staples["lök"].max_amount is None
    rules = parse_rules({"basvaror": {"varor": {"ris": "nej", "pasta": False, "bulgur": ""}}})
    assert set(rules.staples) == {"bulgur"} and rules.staples["bulgur"].max_amount is None
    for bad in ("mycket", "2 förp", "5", "5 kg potatis", 5):
        with pytest.raises(RulesError):
            parse_rules({"basvaror": {"varor": {"potatis": bad}}})
    for bad in ({"min_besparing": 1}, {"max_gånger_behovet": 0.5}, {"max_merkostnad": 50}):
        with pytest.raises(RulesError):
            parse_rules({"basvaror": bad})


def test_basvaror_utom_is_configurable():
    rules = parse_rules({"basvaror": {"utom": ["färsk"], "varor": ["pasta"]}})
    assert rules.stock_up_for("färsk pasta", "Skafferi") is None
    assert rules.stock_up_for("rostad pasta", "Skafferi") is rules.staples["pasta"]


def test_storpack_limits_are_configurable_and_never_negative():
    rules = parse_rules({"standard": {"storpack_max_merkostnad": "0,3", "storpack_max_merkostnad_kr": 50}})
    assert rules.stock_up.allowance(100) == 30 and rules.stock_up.allowance(1000) == 50
    with pytest.raises(RulesError):
        parse_rules({"standard": {"storpack_max_merkostnad_kr": -1}})


def test_tillat_fryst_lifts_the_frozen_exclusion_for_listed_items_only():
    rules = load_rules(REPO_RULES)
    frozen = product(1, "Garant Kyckling Bröstfilé Fryst", extra="1000 g")
    fresh = product(2, "Kronfågel Kycklingfilé", extra="925 g")
    chicken = rules.rule_for("kycklingfilé", "Kött & Fisk")
    assert "fryst" not in chicken.exclude and "marinerad" in chicken.exclude
    assert filter_candidates([frozen, fresh], chicken)[0] == [frozen, fresh]
    beef = rules.rule_for("högrev", "Kött & Fisk")
    assert "fryst" in beef.exclude and filter_candidates([frozen, fresh], beef)[0] == [fresh]


def test_tillat_fryst_is_parsed_and_defaults_to_empty():
    assert parse_rules({}).frozen_ok_words == ()
    rules = parse_rules({"kategorier": {"Kött & Fisk": {"uteslut": ["fryst"]}}, "tillåt_fryst": "laxfilé"})
    assert rules.rule_for("laxfilé", "Kött & Fisk").exclude == ()
