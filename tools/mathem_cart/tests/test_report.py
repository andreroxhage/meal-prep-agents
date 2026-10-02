from datetime import datetime, timedelta, timezone

from mathem_cart.plan_model import ApplyResult, Need, PlanLine, Undecided
from mathem_cart.report import fmt_counts, fmt_need, fmt_num, reason_counts, render_report, source_counts
from tests.test_plan_model import sample_plan  # noqa: reuse

TZ = timezone(timedelta(hours=2))


def test_report_sections_and_swedish_numbers():
    text = render_report(sample_plan())
    assert text.startswith("# Steg 6 — Mathem-varukorg (experimentell)")
    assert "Ingen beställning görs" in text
    assert ("| vispgrädde | 300 ml | Garant Vispgrädde 36% (6851) | 5 dl | 1 | 27,20 kr | 54,40 kr/l | — | pin "
            "|  | överköp 67 % |") in text
    assert "## Behöver beslut" in text and "### kycklingfilé — 1,2 kg (matchning behövs)" in text
    assert "1. Kronfågel Kycklingfilé (id 1) · 700 g · 72,50 kr · 103,57 kr/kg · 2 för 99 kr" in text
    assert "p 0" not in text and "läge" not in text
    assert 'mathem-cart pin "kycklingfilé" <id>' in text
    assert "## Hoppade över\n- dill" in text
    assert "## Ej med\n- Salt\n- Svartpeppar" in text
    assert "totalt 27,20 kr" in text


def test_report_without_undecided_has_no_decision_section():
    plan = sample_plan()
    plan.undecided = []
    assert "## Behöver beslut" not in render_report(plan)


def test_report_with_apply_result_ok_and_diff():
    ok = ApplyResult(datetime(2026, 9, 24, 18, 30, tzinfo=TZ), {6851: 1}, {6851: 1}, [])
    assert "✅ Alla 1 rader finns i varukorgen med rätt antal." in render_report(sample_plan(), ok)
    bad = ApplyResult(datetime(2026, 9, 24, 18, 30, tzinfo=TZ), {6851: 1}, {}, ["Garant Vispgrädde 36% (6851): saknas i varukorgen"],
                      error="avbröts: HTTP 500")
    text = render_report(sample_plan(), bad)
    assert "⚠️" in text and "saknas i varukorgen" in text and "avbröts: HTTP 500" in text
    assert "Töm varukorgen" in text


def test_formatters():
    assert fmt_num(1.2) == "1,2"
    assert fmt_num(300.0) == "300"
    assert fmt_need(Need(1200, "g")) == "1,2 kg"
    assert fmt_need(Need(1500, "ml")) == "1,5 l"
    assert fmt_need(Need(300, "ml")) == "300 ml"
    assert fmt_need(Need(2, "förp")) == "2 förp"
    assert fmt_need(Need(None, None)) == "okänt"


def test_empty_plan_still_has_cart_section_and_omits_empty_sections():
    plan = sample_plan()
    plan.lines, plan.undecided, plan.skipped, plan.excluded, plan.warnings = [], [], [], [], []
    plan.total_kr = 0.0
    text = render_report(plan)
    assert "## I varukorgen" in text
    for heading in ("## Behöver beslut", "## Hoppade över", "## Ej med", "## Varningar", "## Resultat"):
        assert heading not in text


def test_beslut_and_motivering_columns():
    plan = sample_plan()
    plan.lines.append(PlanLine("högrev", Need(1800, "g"), "Kött & Fisk", 2737, "Scan Högrev Bit", "ca 1200 g", 2,
                               378.0, "157.50 kr/kg", None, 0.33, "haiku", [],
                               reason="Scan Högrev Bit är hel bit som listan kräver " + "x" * 80))
    text = render_report(plan)
    assert ("| Vara | Behov | Produkt | Förp. | Antal | Kostnad | Jämförpris | Kampanj | Beslut | Motivering "
            "| Flaggor |") in text
    assert ("| vispgrädde | 300 ml | Garant Vispgrädde 36% (6851) | 5 dl | 1 | 27,20 kr | 54,40 kr/l | — | pin "
            "|  | överköp 67 % |") in text
    row = next(r for r in text.splitlines() if r.startswith("| högrev |"))
    reason = row.split(" | ")[9]
    assert len(reason) == 80 and reason.endswith("…")


def test_header_counts_per_source_and_reason():
    plan = sample_plan()
    plan.undecided.append(Undecided("dill", Need(1, "st"), "Grönsaker", "osäker", [], note="knippe eller kruka?"))
    text = render_report(plan)
    assert "Beslut: pin 1 · fast 0 · haiku 0 · sonnet 0" in text
    assert "Oavgjorda: matchning behövs 1 · osäker 1" in text
    assert "### dill — 1 st (osäker)\nModellen: knippe eller kruka?" in text


def test_counts():
    lines = sample_plan().lines * 2
    assert source_counts(lines) == {"pin": 2, "fast": 0, "haiku": 0, "sonnet": 0}
    assert fmt_counts({"pin": 3, "haiku": 40}) == "pin 3 · haiku 40"
    und = sample_plan().undecided * 3
    assert reason_counts(und) == {"matchning behövs": 3}
