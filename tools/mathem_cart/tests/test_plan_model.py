import json
from datetime import datetime, timedelta, timezone

import pytest

from mathem_cart.plan_model import ApplyResult, Candidate, Need, Plan, PlanLine, Undecided

TZ = timezone(timedelta(hours=2))


def sample_plan():
    line = PlanLine("vispgrädde", Need(300, "ml"), "Mejeri & Ägg", 6851, "Garant Vispgrädde 36%", "5 dl", 1,
                    27.20, "54.40 kr/l", None, 0.67, "pin", ["överköp"])
    und = Undecided("kycklingfilé", Need(1200, "g"), "Kött & Fisk", "matchning behövs",
                    [Candidate(1, "Kronfågel Kycklingfilé", "700 g", 72.5, "103.57 kr/kg", "2 för 99 kr")])
    return Plan("2026-09-21", datetime(2026, 9, 24, 18, 2, 11, tzinfo=TZ), [line], [und],
                ["dill"], ["Salt", "Svartpeppar"], [], 27.20)


def test_json_keys_match_spec():
    d = sample_plan().to_dict()
    assert list(d) == ["vecka", "skapad", "rader", "undecided", "hoppade", "ej_med", "varningar", "total_kr"]
    assert d["skapad"] == "2026-09-24T18:02:11+02:00"
    assert d["rader"][0] == {"vara": "vispgrädde", "behov": {"mängd": 300, "enhet": "ml"},
                             "kategori": "Mejeri & Ägg", "produkt_id": 6851, "namn": "Garant Vispgrädde 36%",
                             "förpackning": "5 dl", "antal": 1, "kostnad_kr": 27.20, "jämförpris": "54.40 kr/l",
                             "kampanj": None, "överköp": 0.67, "beslut": "pin", "flaggor": ["överköp"],
                             "motivering": None}
    assert list(d["rader"][0])[-1] == "motivering"
    assert d["undecided"][0]["kandidater"][0] == {"produkt_id": 1, "namn": "Kronfågel Kycklingfilé",
                                                  "förpackning": "700 g", "pris": 72.5, "jämförpris": "103.57 kr/kg",
                                                  "kampanj": "2 för 99 kr"}


def test_model_reason_round_trips(tmp_path):
    plan = sample_plan()
    plan.lines[0].decision, plan.lines[0].reason = "haiku", "Garant Vispgrädde 36% — vanlig vispgrädde"
    plan.undecided[0].note = "fetthalt oklar"
    d = plan.to_dict()
    assert d["rader"][0]["beslut"] == "haiku" and d["rader"][0]["motivering"].startswith("Garant")
    assert list(d["undecided"][0]) == ["vara", "behov", "kategori", "orsak", "motivering", "kandidater"]
    path = tmp_path / "plan.json"
    plan.write(path)
    assert Plan.read(path) == plan


def test_plan_without_motivering_still_reads():
    d = sample_plan().to_dict()
    del d["rader"][0]["motivering"], d["undecided"][0]["motivering"]
    assert Plan.from_dict(d) == sample_plan()


def test_old_plan_with_läge_and_p_still_reads():
    d = sample_plan().to_dict()
    d["läge"] = "lär"
    d["undecided"][0]["kandidater"][0]["p"] = 0.71
    assert Plan.from_dict(d) == sample_plan()


def test_round_trip(tmp_path):
    path = tmp_path / "06-mathem-plan.json"
    sample_plan().write(path)
    assert json.loads(path.read_text(encoding="utf-8"))["vecka"] == "2026-09-21"
    assert Plan.read(path) == sample_plan()


def test_naive_created_is_rejected(tmp_path):
    d = sample_plan().to_dict()
    d["skapad"] = "2026-09-24T18:02:11"
    with pytest.raises(ValueError, match="tidszon"):
        Plan.from_dict(d)


def test_need_keeps_integers_and_unknown():
    assert Need(300.0, "ml").to_dict() == {"mängd": 300, "enhet": "ml"}
    assert isinstance(Need(300.0, "ml").to_dict()["mängd"], int)
    assert Need(1.5, "st").to_dict() == {"mängd": 1.5, "enhet": "st"}
    assert Need(None, None).to_dict() == {"mängd": None, "enhet": None}
    assert Need.from_dict({"mängd": None, "enhet": None}) == Need(None, None)


def test_apply_result_ok():
    t = datetime(2026, 9, 24, 18, 30, tzinfo=TZ)
    assert ApplyResult(t, {1: 2}, {1: 2}, []).ok
    assert not ApplyResult(t, {1: 2}, {1: 1}, ["diff"]).ok
    assert not ApplyResult(t, {1: 2}, {1: 2}, [], error="avbröts").ok
