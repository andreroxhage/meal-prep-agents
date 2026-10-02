import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mathem_cart.candidates import (CANDIDATE_FILE, Pending, answer_path, build_candidate_file,
                                    read_round, vara_id, write_round)
from mathem_cart.decider import DecideDeps, DecideError, decide
from mathem_cart.mathem.models import Product
from mathem_cart.plan_model import Need, PlanLine, Undecided
from mathem_cart.shopping_list import Item

NOW = datetime(2026, 9, 24, 21, 10, tzinfo=timezone(timedelta(hours=2)))


def product(pid, name=None):
    return Product.from_api({"id": pid, "full_name": name or f"Produkt {pid}", "name_extra": "1 st",
                             "gross_price": "10", "availability": {"is_available": True, "code": "available"}})


class Fake:
    """Stands in for the planner: a search catalogue plus line/undecided factories."""

    def __init__(self, catalog):
        self.catalog = {term: list(products) for term, products in catalog.items()}
        self.searched = []
        self.undecided = []                                  # (vara, reason, candidate ids, note)

    def candidates_for(self, item, term):
        self.searched.append(term)
        return list(self.catalog.get(term, []))

    def line_for(self, item, accepted, decision, reason=None):
        p = accepted[0]
        return PlanLine(item=item.name, need=Need(1, "st"), category=item.category, product_id=p.id,
                        name=p.full_name, package="1 st", count=1, cost_kr=10.0, unit_price=None, deal=None,
                        overshoot=0.0, decision=decision, flags=[], reason=reason)

    def undecided_for(self, item, reason, products, note=None):
        self.undecided.append((item.name, reason, [p.id for p in products], note))
        return Undecided(item=item.name, need=Need(1, "st"), category=item.category, reason=reason,
                         candidates=[], note=note)


def make_item(name):
    return Item(name=name, key=name.casefold(), amount=1, unit="st", category="Grönsaker")


def setup(tmp_path, spec):
    """spec: [(name, [product ids])] -> fake, pending, round-1 file (written)."""
    fake = Fake({name.casefold(): [product(i) for i in ids] for name, ids in spec})
    pending = [Pending(make_item(name), vara_id(i), name.casefold(), [product(pid) for pid in ids])
               for i, (name, ids) in enumerate(spec, 1)]
    file, _ = build_candidate_file("w", 1, pending, now=NOW)
    write_round(tmp_path, file)
    return fake, pending, file


def run(tmp_path, fake, pending):
    return decide(DecideDeps(week_dir=tmp_path, week="w", now=NOW, pending=pending,
                             candidates_for=fake.candidates_for, line_for=fake.line_for,
                             undecided_for=fake.undecided_for))


def entry(vid, beslut="vald", ids=(), reason="ok", term=None):
    return {"vara_id": vid, "beslut": beslut, "godkända": list(ids), "motivering": reason, "ny_sökterm": term}


def write_answer(tmp_path, file, part, entries):
    path = tmp_path / answer_path(file["omgång"], part)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kandidat_id": file["kandidat_id"], "omgång": file["omgång"], "batch": part,
                                "svar": entries}, ensure_ascii=False), encoding="utf-8")


def test_round_one_picks_become_haiku_lines(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1, 2]), ("Lök", [3])])
    write_answer(tmp_path, file, 1, [entry("v01", ids=[2], reason="plommon"), entry("v02", ids=[3])])
    result = run(tmp_path, fake, pending)
    assert result.status == "klar" and result.round_no == 1
    assert [(o.product_id, o.decision, o.reason) for o in result.outcomes.values()] == [(2, "haiku", "plommon"),
                                                                                         (3, "haiku", "ok")]


def test_no_answer_files_at_all_means_matchning_saknas(tmp_path):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1]), ("Lök", [3])])
    result = run(tmp_path, fake, pending)
    assert result.status == "klar"
    assert [o.reason for o in result.outcomes.values()] == ["matchning saknas", "matchning saknas"]


def test_a_missing_batch_is_resent_once_then_undecided(tmp_path):
    spec = [(f"Vara {i}", [i]) for i in range(1, 14)]          # 13 items -> two batches (7 + 6)
    fake, pending, file = setup(tmp_path, spec)
    write_answer(tmp_path, file, 1, [entry(vara_id(i), ids=[i]) for i in range(1, 8)])
    first = run(tmp_path, fake, pending)
    assert first.status == "skicka om" and first.outcomes == {}
    assert [(r.part, r.path, r.problem) for r in first.resend] == [
        (2, ".mathem-matchning/omgang-1/batch-02.json", "saknas")]
    second = run(tmp_path, fake, pending)
    assert second.status == "klar"
    assert [o.decision for o in list(second.outcomes.values())[:7]] == ["haiku"] * 7
    assert {o.reason for o in list(second.outcomes.values())[7:]} == {"matchning saknas"}


def test_an_invalid_file_is_resent_with_its_error(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1])])
    (tmp_path / answer_path(1, 1)).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / answer_path(1, 1)).write_text("inte json", encoding="utf-8")
    first = run(tmp_path, fake, pending)
    assert first.status == "skicka om" and first.resend[0].problem.startswith("ogiltigt: ")
    write_answer(tmp_path, file, 1, [entry("v01", ids=[1])])
    assert run(tmp_path, fake, pending).outcomes["v01"].decision == "haiku"


def test_invalid_twice_is_ogiltigt_svar(tmp_path):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1])])
    (tmp_path / answer_path(1, 1)).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / answer_path(1, 1)).write_text("inte json", encoding="utf-8")
    run(tmp_path, fake, pending)
    assert run(tmp_path, fake, pending).outcomes["v01"].reason == "ogiltigt svar"


def test_unsure_goes_to_the_reviewer_in_round_two(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2]), ("Lök", [3])])
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "fetthalt oklar"), entry("v02", ids=[3])])
    result = run(tmp_path, fake, pending)
    assert result.status == "omgång 2" and result.candidate_file == tmp_path / CANDIDATE_FILE
    second = read_round(tmp_path)
    assert second["omgång"] == 2 and second["batcher"] == []
    assert second["granskning"]["varor"][0]["tidigare"] == {"beslut": "osäker", "godkända": [1],
                                                            "motivering": "fetthalt oklar"}
    assert read_round(tmp_path, 1) == file


def test_new_search_term_goes_to_a_round_two_batch(tmp_path):
    fake, pending, file = setup(tmp_path, [("Perillablad", []), ("Tomat", [1])])
    fake.catalog["shiso"] = [product(50, "Shiso Grön")]
    write_answer(tmp_path, file, 1, [entry("v01", "ingen_passar", [], "inget relevant", "shiso"),
                                     entry("v02", "ingen_passar", [], "fel", "körsbärstomat")])
    result = run(tmp_path, fake, pending)
    assert result.status == "omgång 2" and "shiso" in fake.searched
    second = read_round(tmp_path)
    varor = [v for b in second["batcher"] for v in b["varor"]]
    assert [(v["vara_id"], v["sökterm"], [c["produkt_id"] for c in v["kandidater"]]) for v in varor] == [
        ("v01", "shiso", [50])]


def test_new_term_without_hits_is_undecided_directly(tmp_path):
    fake, pending, file = setup(tmp_path, [("Perillablad", [])])
    write_answer(tmp_path, file, 1, [entry("v01", "ingen_passar", [], "inget", "shiso")])
    result = run(tmp_path, fake, pending)
    assert result.status == "klar" and result.outcomes["v01"].reason == "inga kandidater"
    assert "shiso" in result.outcomes["v01"].note


def test_no_fit_without_term_is_undecided_with_the_reason(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1])])
    write_answer(tmp_path, file, 1, [entry("v01", "ingen_passar", [], "bara soltorkade")])
    out = run(tmp_path, fake, pending).outcomes["v01"]
    assert out.reason == "ingen passar" and out.note == "bara soltorkade"


def _round_two(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2]), ("Perillablad", []), ("Tomat", [5]), ("Dill", [7])])
    fake.catalog["shiso"] = [product(50)]
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "fetthalt"),
                                     entry("v02", "ingen_passar", [], "inget", "shiso"),
                                     entry("v03", ids=[5]),
                                     entry("v04", "osäker", [7], "knippe?")])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    return fake, pending, read_round(tmp_path)


def test_full_second_round(tmp_path):
    fake, pending, second = _round_two(tmp_path)
    write_answer(tmp_path, second, "granskning", [entry("v01", ids=[1], reason="36 %"),
                                                  entry("v04", "osäker", [7], "kruka eller knippe")])
    write_answer(tmp_path, second, 1, [entry("v02", ids=[50], reason="shiso = perilla")])
    result = run(tmp_path, fake, pending)
    assert result.status == "klar" and result.round_no == 2
    out = result.outcomes
    assert set(out) == {p.vara_id for p in pending}
    assert (out["v01"].decision, out["v01"].product_id) == ("sonnet", 1)
    assert (out["v02"].decision, out["v02"].product_id) == ("haiku", 50)
    assert out["v03"].decision == "haiku"
    assert (out["v04"].reason, out["v04"].note) == ("osäker", "kruka eller knippe")


def test_a_third_round_is_refused(tmp_path):
    fake, pending, second = _round_two(tmp_path)
    write_answer(tmp_path, second, "granskning", [entry("v01", ids=[1]), entry("v04", ids=[7])])
    write_answer(tmp_path, second, 1, [entry("v02", "ingen_passar", [], "nej", "perilla")])
    result = run(tmp_path, fake, pending)
    assert result.status == "klar" and result.outcomes["v02"].reason == "ogiltig sökterm"


def test_round_number_above_two_is_an_error(tmp_path):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1])])
    third, _ = build_candidate_file("w", 3, pending, now=NOW)
    write_round(tmp_path, third)
    with pytest.raises(DecideError, match="högst 2"):
        run(tmp_path, fake, pending)


def test_sold_out_approved_product_goes_to_review(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1, 2])])
    fake.catalog["tomat"] = [product(2)]                      # 1 sold out since plan
    write_answer(tmp_path, file, 1, [entry("v01", ids=[1])])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    assert read_round(tmp_path)["granskning"]["varor"][0]["vara_id"] == "v01"


def test_approved_product_must_be_in_the_current_search(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1, 2])])
    fake.catalog["tomat"] = [product(2)]
    write_answer(tmp_path, file, 1, [entry("v01", ids=[1, 2])])
    assert run(tmp_path, fake, pending).outcomes["v01"].product_id == 2


def test_changed_shopping_list_is_refused(tmp_path):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1]), ("Lök", [3])])
    moved = [Pending(make_item("Gurka"), "v01", "gurka", []), pending[1]]
    with pytest.raises(DecideError, match="handlingslistan har ändrats"):
        run(tmp_path, fake, moved)


def test_edited_candidate_file_is_refused(tmp_path):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1])])
    data = json.loads((tmp_path / CANDIDATE_FILE).read_text(encoding="utf-8"))
    data["batcher"][0]["varor"][0]["kandidater"].append({"produkt_id": 666, "namn": "X", "förpackning": "",
                                                         "märkning": []})
    (tmp_path / CANDIDATE_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DecideError):
        run(tmp_path, fake, pending)


def test_pinned_since_plan_is_ignored_and_new_items_are_missing(tmp_path):
    fake, pending, file = setup(tmp_path, [("Tomat", [1]), ("Lök", [3])])
    write_answer(tmp_path, file, 1, [entry("v01", ids=[1]), entry("v02", ids=[3])])
    extra = Pending(make_item("Dill"), "v03", "dill", [product(9)])
    result = run(tmp_path, fake, [pending[1], extra])        # v01 was pinned by the user meanwhile
    assert set(result.outcomes) == {"v02", "v03"}
    assert result.outcomes["v02"].decision == "haiku" and result.outcomes["v03"].reason == "matchning saknas"


def test_rerun_is_idempotent(tmp_path):
    fake, pending, second = _round_two(tmp_path)
    write_answer(tmp_path, second, "granskning", [entry("v01", ids=[1]), entry("v04", ids=[7])])
    write_answer(tmp_path, second, 1, [entry("v02", ids=[50])])
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    first, again = run(tmp_path, fake, pending), run(tmp_path, fake, pending)
    assert first.outcomes == again.outcomes
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")} == before


def test_decider_has_no_access_to_pins():
    source = (Path(__file__).parents[1] / "mathem_cart" / "decider.py").read_text(encoding="utf-8")
    assert "pins" not in source.replace("pinned", "")


# --- review findings ------------------------------------------------------------------

def test_round_one_answers_are_frozen_once_round_two_exists(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2]), ("Lök", [3])])
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "oklart"), entry("v02", ids=[3])])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    second = read_round(tmp_path)
    write_answer(tmp_path, second, "granskning", [entry("v01", "ingen_passar", [], "fel fetthalt")])
    write_answer(tmp_path, file, 1, [entry("v01", ids=[1]), entry("v02", ids=[3])])   # round 1 rewritten
    with pytest.raises(DecideError, match="omgång 1 har ändrats"):
        run(tmp_path, fake, pending)


def test_unchanged_round_one_answers_still_decide_round_two(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2]), ("Lök", [3])])
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "oklart"), entry("v02", ids=[3])])
    run(tmp_path, fake, pending)
    write_answer(tmp_path, read_round(tmp_path), "granskning", [entry("v01", "ingen_passar", [], "fel fetthalt")])
    out = run(tmp_path, fake, pending).outcomes
    assert (out["v01"].reason, out["v01"].note) == ("ingen passar", "fel fetthalt")


def test_round_one_copy_over_the_current_round_is_refused(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2])])
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "oklart")])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    copy = tmp_path / ".mathem-matchning" / "omgang-1" / "kandidater.json"
    (tmp_path / CANDIDATE_FILE).write_text(copy.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(DecideError, match="omgång 2 finns redan"):
        run(tmp_path, fake, pending)


@pytest.mark.parametrize("record", ["[]", "inte json", '{"delar": [], "kontroll": "000000000000"}'])
def test_a_reset_resend_record_does_not_allow_another_resend(tmp_path, record):
    fake, pending, _ = setup(tmp_path, [("Tomat", [1])])
    (tmp_path / answer_path(1, 1)).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / answer_path(1, 1)).write_text("inte json", encoding="utf-8")
    assert run(tmp_path, fake, pending).status == "skicka om"
    (tmp_path / ".mathem-matchning" / "omgang-1" / "omsändning.json").write_text(record, encoding="utf-8")
    result = run(tmp_path, fake, pending)
    assert result.status == "klar" and result.outcomes["v01"].reason == "ogiltigt svar"
    assert any("omsändning.json" in w for w in result.warnings)


def test_new_term_without_hits_keeps_its_reason_when_round_two_runs(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1]), ("Perillablad", [])])
    write_answer(tmp_path, file, 1, [entry("v01", "osäker", [1], "fetthalt"),
                                     entry("v02", "ingen_passar", [], "inget", "shiso")])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    write_answer(tmp_path, read_round(tmp_path), "granskning", [entry("v01", ids=[1])])
    out = run(tmp_path, fake, pending).outcomes["v02"]
    assert out.reason == "inga kandidater" and "shiso" in out.note


def test_round_two_undecided_research_item_shows_the_new_candidates(tmp_path):
    fake, pending, file = setup(tmp_path, [("Perillablad", [])])
    fake.catalog["shiso"] = [product(50), product(51)]
    write_answer(tmp_path, file, 1, [entry("v01", "ingen_passar", [], "inget", "shiso")])
    assert run(tmp_path, fake, pending).status == "omgång 2"
    write_answer(tmp_path, read_round(tmp_path), 1, [entry("v01", "osäker", [50], "grön eller röd?")])
    fake.undecided.clear()
    run(tmp_path, fake, pending)
    assert fake.undecided == [("Perillablad", "osäker", [50, 51], "grön eller röd?")]


def test_round_two_cut_candidates_are_logged(tmp_path):
    fake, pending, file = setup(tmp_path, [("Perillablad", [])])
    fake.catalog["shiso"] = [product(i) for i in range(100, 125)]
    write_answer(tmp_path, file, 1, [entry("v01", "ingen_passar", [], "inget", "shiso")])
    result = run(tmp_path, fake, pending)
    assert result.status == "omgång 2"
    assert len(read_round(tmp_path)["batcher"][0]["varor"][0]["kandidater"]) == 20
    assert any("Perillablad +5" in w and "15" in w for w in result.warnings)


def test_accepted_products_keep_the_search_order(tmp_path):
    fake, pending, file = setup(tmp_path, [("Grädde", [1, 2, 3])])
    seen = []
    fake.line_for = lambda item, accepted, decision, reason=None: seen.append([p.id for p in accepted]) or \
        fake.undecided_for(item, "ingen förpackning går att räkna", accepted, reason)
    write_answer(tmp_path, file, 1, [entry("v01", ids=[3, 1])])
    run(tmp_path, fake, pending)
    assert seen == [[1, 3]]
