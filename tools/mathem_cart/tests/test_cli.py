import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mathem_cart import cli
from mathem_cart.mathem.session import MathemSession
from mathem_cart.plan_model import Candidate
from mathem_cart.shopping_list import parse_line

FIX = Path(__file__).parent / "fixtures"
LIST = "## Mejeri & Ägg\n- 3 dl vispgrädde\n## Kött & Fisk\n- 1,2 kg kycklingfilé\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "tools" / "mathem_cart").mkdir(parents=True)
    (tmp_path / "tools" / "mathem_cart" / "pyproject.toml").write_text("")
    week = tmp_path / "2026-09-21"
    week.mkdir()
    (week / "03-handlingslista.md").write_text(LIST, encoding="utf-8")
    (tmp_path / "2026-09-14").mkdir()
    monkeypatch.setenv("MATHEM_CART_ROOT", str(tmp_path))
    monkeypatch.setenv("MATHEM_BOT_CONTACT", "https://example.org")
    for var in ("MATHEM_EMAIL", "MATHEM_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    pins = tmp_path / "pins.yaml"
    return tmp_path, week, ["--pins", str(pins)]


def fake_session_factory(requests):
    fixtures = {"vispgrädde": "search-vispgradde.json", "kycklingfilé": "search-kycklingfile.json"}

    def handler(request):
        requests.append(request)
        name = fixtures.get(request.url.params.get("q"))
        if request.url.path.endswith("/search/mixed/") and name:
            return httpx.Response(200, json=json.loads((FIX / name).read_text(encoding="utf-8")))
        return httpx.Response(200, json={"type": "search", "attributes": {"has_more_items": False}, "items": []})

    return lambda contact: MathemSession(contact, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                         sleep=lambda s: None)


def test_plan_uses_cache_on_second_run(repo, monkeypatch):
    root, week, extra = repo
    requests = []
    monkeypatch.setattr(cli, "make_session", fake_session_factory(requests))
    assert cli.main(["plan", "--no-input", *extra]) == 4
    first = len(requests)
    assert cli.main(["plan", "--no-input", *extra]) == 4
    assert len(requests) == first and (week / ".mathem-cache").is_dir()


def test_plan_hoppa_all_exits_0(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["plan", "--no-input", "--hoppa", "vispgrädde", "--hoppa", "kycklingfilé", *extra]) == 0


def test_plan_without_contact_exits_1(repo, monkeypatch, capsys):
    monkeypatch.delenv("MATHEM_BOT_CONTACT")
    assert cli.main(["plan", "--no-input", *repo[2]]) == 1
    assert "MATHEM_BOT_CONTACT" in capsys.readouterr().err


def test_plan_missing_shopping_list_exits_1(repo, monkeypatch, capsys):
    root, week, extra = repo
    (week / "03-handlingslista.md").unlink()
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["plan", "--no-input", *extra]) == 1
    assert "03-handlingslista.md" in capsys.readouterr().err


def test_pin_command(repo):
    root, week, extra = repo
    assert cli.main(["pin", "Vispgrädde", "6851", *extra]) == 0
    assert cli.main(["pin", "kycklingfilé", "--sök", "kycklingbröstfilé", *extra]) == 0
    assert cli.main(["pin", "krossade tomater", "9876", "--fast", *extra]) == 0
    text = Path(extra[1]).read_text(encoding="utf-8")
    assert "vispgrädde" in text and "6851" in text and "kycklingbröstfilé" in text and "fast: 9876" in text


def test_pin_without_product_or_search_exits_1(repo, capsys):
    root, week, extra = repo
    assert cli.main(["pin", "vispgrädde", *extra]) == 1
    assert not Path(extra[1]).exists()


def write_plan(week, created, lines=1):
    rows = [{"vara": "vispgrädde", "behov": {"mängd": 300, "enhet": "ml"}, "kategori": "Mejeri & Ägg",
             "produkt_id": 6851, "namn": "Garant Vispgrädde 36%", "förpackning": "5 dl", "antal": 1,
             "kostnad_kr": 27.2, "jämförpris": "54.40 kr/l", "kampanj": None, "överköp": 0.67,
             "beslut": "pin", "flaggor": []}][:lines]
    (week / "06-mathem-plan.json").write_text(json.dumps({
        "vecka": week.name, "skapad": created.isoformat(), "rader": rows, "undecided": [],
        "hoppade": [], "ej_med": [], "varningar": [], "total_kr": 27.2 if rows else 0}), encoding="utf-8")


def test_apply_stale_plan_exits_3_without_network(repo, monkeypatch):
    root, week, extra = repo
    write_plan(week, datetime.now(timezone.utc) - timedelta(hours=30))
    monkeypatch.setattr(cli, "make_session", lambda c: pytest.fail("no session for a stale plan"))
    monkeypatch.setenv("MATHEM_EMAIL", "a@b.se")
    monkeypatch.setenv("MATHEM_PASSWORD", "x")
    assert cli.main(["apply", *extra]) == 3


def test_apply_missing_credentials_exits_1_and_names_variable(repo, monkeypatch, capsys):
    root, week, extra = repo
    write_plan(week, datetime.now(timezone.utc))
    monkeypatch.setattr(cli, "make_session", lambda c: pytest.fail("no session without credentials"))
    assert cli.main(["apply", *extra]) == 1
    assert "MATHEM_EMAIL" in capsys.readouterr().err


def test_apply_empty_plan_needs_no_network(repo, monkeypatch):
    root, week, extra = repo
    write_plan(week, datetime.now(timezone.utc), lines=0)
    monkeypatch.setattr(cli, "make_session", lambda c: pytest.fail("no network for an empty plan"))
    assert cli.main(["apply", *extra]) == 0


def test_latest_week_is_default(repo):
    assert cli.latest_week(repo[0]).name == "2026-09-21"


def test_terminal_asker_maps_keys_to_answers(monkeypatch, capsys):
    item = parse_line("3 dl vispgrädde", "Mejeri & Ägg")
    cands = [Candidate(6851, "Garant Vispgrädde 36%", "5 dl", 27.2, "54.40 kr/l", None),
             Candidate(2380, "Arla Vispgrädde 40%", "3 dl", 24.95, "83.17 kr/l", "2 för 40 kr")]
    replies = iter(["x", "9", "2", "f1", "s", "grädde 36", "h"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    asker = cli.TerminalAsker()
    assert asker.ask(item, cands) == cli.Answer("accept", 2380)      # "x" and "9" re-prompt
    assert asker.ask(item, cands) == cli.Answer("fixed", 6851)
    assert asker.ask(item, cands) == cli.Answer("search", term="grädde 36")
    assert asker.ask(item, cands) == cli.Answer("skip")
    out = capsys.readouterr().out
    assert "1) Garant Vispgrädde 36% · 5 dl · 27,20 kr · 54,40 kr/l · —" in out


def test_eval_is_gone(repo):
    assert cli.main(["eval", *repo[2]]) == 1


def test_old_matching_block_warns_once(repo, monkeypatch, capsys):
    root, week, extra = repo
    rules = root / "regler.yaml"
    rules.write_text(
        "säkerhet:\n  max_antal_per_rad: 10\n  plan_max_ålder_h: 24\n"
        "matchning:\n  läge: auto\n  tröskel: 0.9\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", "--regler", str(rules), *extra])
    assert capsys.readouterr().err.count("matchning.läge") == 1


CANDIDATES = "06-mathem-kandidater.json"


def answer_all(week, beslut="vald"):
    file = json.loads((week / CANDIDATES).read_text(encoding="utf-8"))
    parts = [(b["batch"], b) for b in file["batcher"]]
    if file["granskning"]:
        parts.append(("granskning", file["granskning"]))
    for pid, part in parts:
        path = week / part["svarsfil"]
        path.parent.mkdir(parents=True, exist_ok=True)
        svar = [{"vara_id": v["vara_id"], "beslut": beslut,
                 "godkända": [] if beslut == "ingen_passar" else [c["produkt_id"] for c in v["kandidater"]],
                 "motivering": "test", "ny_sökterm": None} for v in part["varor"]]
        path.write_text(json.dumps({"kandidat_id": file["kandidat_id"], "omgång": file["omgång"], "batch": pid,
                                    "svar": svar}, ensure_ascii=False), encoding="utf-8")
    return file


def plan_json(week):
    return json.loads((week / "06-mathem-plan.json").read_text(encoding="utf-8"))


def test_plan_exits_4_and_writes_the_candidate_file(repo, monkeypatch, capsys):
    root, week, extra = repo
    requests = []
    monkeypatch.setattr(cli, "make_session", fake_session_factory(requests))
    assert cli.main(["plan", "--no-input", *extra]) == 4
    file = json.loads((week / CANDIDATES).read_text(encoding="utf-8"))
    assert file["omgång"] == 1 and [v["vara_id"] for v in file["batcher"][0]["varor"]] == ["v01", "v02"]
    assert not (week / "06-mathem-plan.json").exists()
    assert "2 varor behöver matchning · omgång 1 · 1 batcher →" in capsys.readouterr().out
    assert all("/search/mixed/" in r.url.path for r in requests)


def test_plan_exit_4_removes_a_stale_plan(repo, monkeypatch):
    root, week, extra = repo
    write_plan(week, datetime.now(timezone.utc))
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["plan", "--no-input", *extra]) == 4
    assert not (week / "06-mathem-plan.json").exists()


def test_plan_with_everything_pinned_writes_the_plan(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["plan", "--no-input", "--hoppa", "kycklingfilé", *extra]) == 4   # vispgrädde needs matching
    visp = json.loads((week / CANDIDATES).read_text(encoding="utf-8"))["batcher"][0]["varor"][0]
    cli.main(["pin", "vispgrädde", str(visp["kandidater"][0]["produkt_id"]), *extra])
    assert cli.main(["plan", "--no-input", "--hoppa", "kycklingfilé", *extra]) in (0, 2)
    assert plan_json(week)["rader"][0]["beslut"] == "pin"
    assert not (week / CANDIDATES).exists()


def test_decide_without_answers_leaves_everything_undecided(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    capsys.readouterr()
    assert cli.main(["decide", "--no-input", *extra]) == 2
    assert [u["orsak"] for u in plan_json(week)["undecided"]] == ["matchning saknas", "matchning saknas"]
    out = capsys.readouterr().out
    assert "Beslut: pin 0 · fast 0 · haiku 0 · sonnet 0" in out and "Oavgjorda: matchning saknas 2" in out


def test_decide_turns_answers_into_haiku_lines_and_never_writes_pins(repo, monkeypatch):
    root, week, extra = repo
    requests = []
    monkeypatch.setattr(cli, "make_session", fake_session_factory(requests))
    cli.main(["plan", "--no-input", *extra])
    answer_all(week)
    pins = Path(extra[1])
    before = pins.read_bytes() if pins.exists() else None
    assert cli.main(["decide", "--no-input", *extra]) == 0
    rows = plan_json(week)["rader"]
    assert [(r["vara"], r["beslut"], r["motivering"]) for r in rows] == [("vispgrädde", "haiku", "test"),
                                                                         ("kycklingfilé", "haiku", "test")]
    assert (pins.read_bytes() if pins.exists() else None) == before            # M3
    assert all("/search/mixed/" in r.url.path for r in requests)               # never login, never cart


def test_decide_round_two_with_the_reviewer(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    answer_all(week, beslut="osäker")
    capsys.readouterr()
    assert cli.main(["decide", "--no-input", *extra]) == 4
    assert "Omgång 2 behövs: 0 batcher, granskning 2 varor →" in capsys.readouterr().out
    assert not (week / "06-mathem-plan.json").exists()
    answer_all(week)
    assert cli.main(["decide", "--no-input", *extra]) == 0
    assert {r["beslut"] for r in plan_json(week)["rader"]} == {"sonnet"}


def test_decide_asks_to_resend_an_invalid_answer_once(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    bad = week / ".mathem-matchning" / "omgang-1" / "batch-01.json"
    bad.write_text("inte json", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["decide", "--no-input", *extra]) == 4
    captured = capsys.readouterr()
    assert "Skicka om: batch 1 → .mathem-matchning/omgang-1/batch-01.json (ogiltigt: " in captured.err
    assert "Omgång 1: 1 svar behöver skickas om" in captured.out
    assert cli.main(["decide", "--no-input", *extra]) == 2
    assert {u["orsak"] for u in plan_json(week)["undecided"]} == {"ogiltigt svar"}


def test_decide_after_a_pin_reuses_stored_answers(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    file = answer_all(week, beslut="ingen_passar")
    cli.main(["decide", "--no-input", *extra])
    listing = sorted(p.name for p in (week / ".mathem-matchning").rglob("*"))
    visp = file["batcher"][0]["varor"][0]["kandidater"][0]["produkt_id"]
    cli.main(["pin", "vispgrädde", str(visp), *extra])
    assert cli.main(["decide", "--no-input", *extra]) == 2
    plan = plan_json(week)
    assert [(r["vara"], r["beslut"]) for r in plan["rader"]] == [("vispgrädde", "pin")]
    assert [u["orsak"] for u in plan["undecided"]] == ["ingen passar"]
    assert sorted(p.name for p in (week / ".mathem-matchning").rglob("*")) == listing


def test_plan_again_discards_old_matching(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    answer_all(week, beslut="osäker")
    cli.main(["decide", "--no-input", *extra])                    # now in round 2
    assert cli.main(["plan", "--no-input", *extra]) == 4
    assert json.loads((week / CANDIDATES).read_text(encoding="utf-8"))["omgång"] == 1
    assert not (week / ".mathem-matchning" / "omgang-2").exists()
    assert not (week / ".mathem-matchning" / "omgang-1" / "batch-01.json").exists()


def test_decide_without_candidate_file(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["decide", "--no-input", *extra]) == 1
    assert "kör plan först" in capsys.readouterr().err
    assert cli.main(["decide", "--no-input", "--hoppa", "vispgrädde", "--hoppa", "kycklingfilé", *extra]) == 0


def test_decide_refuses_a_changed_shopping_list(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    (week / "03-handlingslista.md").write_text("## Mejeri & Ägg\n- 3 dl grädde\n" + LIST, encoding="utf-8")
    assert cli.main(["decide", "--no-input", *extra]) == 1
    assert "handlingslistan har ändrats" in capsys.readouterr().err


class _TTY:
    def isatty(self):
        return True


def test_decide_asks_on_a_terminal(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    replies = iter(["1", "h"])
    monkeypatch.setattr("sys.stdin", _TTY())
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    assert cli.main(["decide", *extra]) == 0
    plan = plan_json(week)
    assert [(r["vara"], r["beslut"]) for r in plan["rader"]] == [("vispgrädde", "pin")]
    assert plan["hoppade"] == ["kycklingfilé"]


def test_plan_names_each_part_file_and_logs_cut_candidates(repo, monkeypatch, capsys):
    from functools import partial
    from mathem_cart import candidates
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    monkeypatch.setattr(cli, "build_candidate_file", partial(candidates.build_candidate_file, cap=10))
    assert cli.main(["plan", "--no-input", *extra]) == 4
    captured = capsys.readouterr()
    match = week / ".mathem-matchning" / "omgang-1"
    assert f"  batch 1: {match / 'batch-01-kandidater.json'} → {match / 'batch-01.json'}" in captured.out
    part = json.loads((match / "batch-01-kandidater.json").read_text(encoding="utf-8"))
    assert [v["vara_id"] for v in part["varor"]] == ["v01", "v02"] and part["batch"] == 1
    cut = [line for line in captured.err.splitlines() if "kandidater efter reglerna" in line]
    assert len(cut) == 1 and cut[0].startswith("Varning: 2 varor hade fler än")
    assert "vispgrädde +" in cut[0] and "kycklingfilé +" in cut[0]


def test_decide_round_two_names_the_review_part_file(repo, monkeypatch, capsys):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    cli.main(["plan", "--no-input", *extra])
    answer_all(week, beslut="osäker")
    capsys.readouterr()
    assert cli.main(["decide", "--no-input", *extra]) == 4
    match = week / ".mathem-matchning" / "omgang-2"
    assert (f"  granskning: {match / 'granskning-kandidater.json'} → {match / 'granskning.json'}"
            in capsys.readouterr().out)


def test_alcohol_is_in_ej_med_and_never_matched(repo, monkeypatch):
    root, week, extra = repo
    (week / "03-handlingslista.md").write_text(LIST + "## Övrigt\n- 1 dl torrt vitt vin\n", encoding="utf-8")
    monkeypatch.setattr(cli, "make_session", fake_session_factory([]))
    assert cli.main(["plan", "--no-input", *extra]) == 4
    file = json.loads((week / CANDIDATES).read_text(encoding="utf-8"))
    assert "torrt vitt vin" not in {v["vara"] for b in file["batcher"] for v in b["varor"]}
    cli.main(["decide", "--no-input", *extra])
    assert "torrt vitt vin (köps på Systembolaget)" in plan_json(week)["ej_med"]
