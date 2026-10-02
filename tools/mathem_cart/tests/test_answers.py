import json

import pytest

from mathem_cart.answers import (BAD_TERM, DUPLICATE, MAX_REASON, UNANSWERED, Verdict, label, load_answer,
                                 validate_answer)

KID = "3f9a1c0e7b2d"
PART = {"batch": 1, "svarsfil": ".mathem-matchning/omgang-1/batch-01.json", "varor": [
    {"vara_id": "v01", "vara": "Högrev", "sökterm": "högrev",
     "kandidater": [{"produkt_id": 2737}, {"produkt_id": 2738}]},
    {"vara_id": "v02", "vara": "Vispgrädde", "sökterm": "vispgrädde", "kandidater": [{"produkt_id": 6851}]},
]}
REVIEW_PART = {"svarsfil": ".mathem-matchning/omgang-2/granskning.json", "varor": [
    {"vara_id": "v02", "vara": "Vispgrädde", "sökterm": "vispgrädde", "kandidater": [{"produkt_id": 6851}],
     "tidigare": {"beslut": "osäker", "godkända": [6851], "motivering": "fetthalt"}}]}


def svar(vid, beslut="vald", godkända=(2737,), motivering="ok", ny=None):
    return {"vara_id": vid, "beslut": beslut, "godkända": list(godkända), "motivering": motivering,
            "ny_sökterm": ny}


def answer(*entries, kid=KID, omgang=1, batch=1):
    return {"kandidat_id": kid, "omgång": omgang, "batch": batch, "svar": list(entries)}


BOTH = (svar("v01"), svar("v02", godkända=[6851]))


def check(data, part=PART, round_no=1, batch=1):
    return validate_answer(data, part, kandidat_id=KID, round_no=round_no, batch=batch)


def test_valid_answer():
    r = check(answer(*BOTH))
    assert r.status == "ok" and r.unresolved == {} and r.warnings == []
    assert r.verdicts == {"v01": Verdict("v01", "vald", (2737,), "ok"),
                          "v02": Verdict("v02", "vald", (6851,), "ok")}


def test_missing_file(tmp_path):
    r = load_answer(tmp_path / "batch-01.json", PART, kandidat_id=KID, round_no=1, batch=1)
    assert r.status == "saknas" and r.verdicts == {}


def test_invalid_json(tmp_path):
    path = tmp_path / "batch-01.json"
    path.write_text('{"kandidat_id": ', encoding="utf-8")
    r = load_answer(path, PART, kandidat_id=KID, round_no=1, batch=1)
    assert r.status == "ogiltig" and "JSON" in r.error


@pytest.mark.parametrize("data", [
    [1, 2],
    answer(*BOTH) | {"svar": "v01"},
    answer(svar("v01", beslut="kanske"), svar("v02")),
    answer(svar("v01", godkända=["2737"]), svar("v02")),
    answer(svar("v01", godkända=[True]), svar("v02")),
    answer(svar("v01", motivering=5), svar("v02")),
    answer(svar("v01", ny=3), svar("v02")),
    answer({"beslut": "vald", "godkända": [], "motivering": ""}, svar("v02")),
    answer("v01", svar("v02")),
])
def test_schema_violation_is_invalid(data):
    r = check(data)
    assert r.status == "ogiltig" and r.error and r.verdicts == {}


@pytest.mark.parametrize("data", [answer(*BOTH, kid="000000000000"), answer(*BOTH, omgang=2),
                                  answer(*BOTH) | {"omgång": True}])
def test_answer_for_another_file_counts_as_missing(data):
    r = check(data)
    assert r.status == "saknas" and r.warnings


def test_batch_mismatch_is_invalid():
    r = check(answer(*BOTH, batch=2))
    assert r.status == "ogiltig" and "batch" in r.error


def test_unanswered_item():
    r = check(answer(svar("v01")))
    assert r.status == "ok" and r.unresolved == {"v02": UNANSWERED} and list(r.verdicts) == ["v01"]


def test_item_answered_twice():
    r = check(answer(svar("v01"), svar("v01", godkända=[2738]), svar("v02", godkända=[6851])))
    assert r.unresolved == {"v01": DUPLICATE} and list(r.verdicts) == ["v02"]


def test_unknown_item_is_ignored_with_warning():
    r = check(answer(*BOTH, svar("v99")))
    assert r.status == "ok" and set(r.verdicts) == {"v01", "v02"}
    assert any("v99" in w for w in r.warnings)


def test_id_outside_the_items_candidates_is_dropped():
    r = check(answer(svar("v01", godkända=[2737, 6851, 999]), svar("v02", godkända=[2737])))
    assert r.verdicts["v01"].approved == (2737,)
    assert r.verdicts["v02"] == Verdict("v02", "osäker", (), "ok")      # nothing left -> osäker
    assert any("6851" in w and "999" in w for w in r.warnings)


def test_vald_with_empty_list_is_unsure():
    r = check(answer(svar("v01", godkända=[]), svar("v02", godkända=[6851])))
    assert r.verdicts["v01"].decision == "osäker"


def test_duplicate_ids_are_collapsed():
    r = check(answer(svar("v01", godkända=[2737, 2737, 2738]), svar("v02", godkända=[6851])))
    assert r.verdicts["v01"].approved == (2737, 2738)


def test_no_fit_carries_no_ids_and_keeps_a_new_term():
    r = check(answer(svar("v01", beslut="ingen_passar", godkända=[2737], ny="  högrev i bit "),
                     svar("v02", godkända=[6851])))
    assert r.verdicts["v01"] == Verdict("v01", "ingen_passar", (), "ok", "högrev i bit")


def test_empty_new_term_counts_as_null():
    r = check(answer(svar("v01", beslut="ingen_passar", godkända=[], ny="  "), svar("v02", godkända=[6851], ny="")))
    assert r.verdicts["v01"].new_term is None and r.verdicts["v02"].decision == "vald"


@pytest.mark.parametrize("entry,round_no,batch,part", [
    (svar("v01", ny="oxbringa"), 1, 1, PART),                                         # with vald
    (svar("v01", beslut="osäker", ny="oxbringa"), 1, 1, PART),                        # with osäker
    (svar("v01", beslut="ingen_passar", godkända=[], ny="oxbringa"), 2, 1, PART),     # round 2
    (svar("v01", beslut="ingen_passar", godkända=[], ny=" HÖGREV "), 1, 1, PART),     # already searched
])
def test_misused_new_term_leaves_the_item_undecided(entry, round_no, batch, part):
    r = check(answer(entry, svar("v02", godkända=[6851]), omgang=round_no, batch=batch), part, round_no, batch)
    assert r.unresolved == {"v01": BAD_TERM} and "v02" in r.verdicts
    assert any("ny_sökterm" in w for w in r.warnings)


def test_reviewer_may_not_propose_a_term():
    data = answer(svar("v02", beslut="ingen_passar", godkända=[], ny="grädde 40"), omgang=2, batch="granskning")
    r = check(data, REVIEW_PART, 2, "granskning")
    assert r.unresolved == {"v02": BAD_TERM}


def test_reviewer_answer():
    data = answer(svar("v02", godkända=[6851], motivering="36 % räcker"), omgang=2, batch="granskning")
    r = check(data, REVIEW_PART, 2, "granskning")
    assert r.status == "ok" and r.verdicts["v02"] == Verdict("v02", "vald", (6851,), "36 % räcker")


def test_long_reason_is_truncated():
    r = check(answer(svar("v01", motivering="x" * 300), svar("v02", godkända=[6851])))
    assert len(r.verdicts["v01"].reason) == MAX_REASON and any("motivering" in w for w in r.warnings)


def test_fenced_json_and_bom_are_read(tmp_path):
    path = tmp_path / "batch-01.json"
    path.write_text("\ufeff```json\n" + json.dumps(answer(*BOTH), ensure_ascii=False) + "\n```\n", encoding="utf-8")
    r = load_answer(path, PART, kandidat_id=KID, round_no=1, batch=1)
    assert r.status == "ok" and set(r.verdicts) == {"v01", "v02"}
    assert any("kodblock" in w for w in r.warnings)


def test_labels():
    assert label(3) == "batch 3" and label("granskning") == "granskning"
