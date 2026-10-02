import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mathem_cart.candidates import (CANDIDATE_FILE, MATCH_DIR, CandidateFileError, Pending, Review, answer_path,
                                    behov_text, build_candidate_file, clear_matching, compute_kandidat_id,
                                    drop_warnings, part_path, read_round, vara_id, write_round)
from mathem_cart.mathem.models import Product
from mathem_cart.shopping_list import Item

NOW = datetime(2026, 9, 24, 21, 10, tzinfo=timezone(timedelta(hours=2)))
PRICE_WORDS = ("price", "pris", "promotion", "kampanj", "discount", "rabatt", "bonus")


def product(pid, name="Scan Högrev Bit", extra="ca 1200 g", labels=("Kött från Sverige",)):
    return Product.from_api({"id": pid, "full_name": name, "name_extra": extra, "gross_price": "189.00",
                             "gross_unit_price": "157.50", "unit_price_quantity_abbreviation": "kg",
                             "promotions": [{"title": "2 för 300 kr"}],
                             "discount": {"maximum_quantity": 2, "undiscounted_gross_price": "210.00"},
                             "client_classifiers": [{"name": label} for label in labels],
                             "availability": {"is_available": True, "code": "available"}})


def item(name="Högrev", amount=1.8, unit="kg", category="Kött & Fisk", note="i bit; Galbi-jjim"):
    return Item(name=name, key=name.casefold(), amount=amount, unit=unit, category=category, note=note)


def pending(n, products=1):
    return [Pending(item(f"Vara {i}"), vara_id(i), f"vara {i}", [product(1000 * i + j) for j in range(products)])
            for i in range(1, n + 1)]


def keys_of(value):
    if isinstance(value, dict):
        return {k.casefold() for k in value} | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def test_vara_id_is_zero_padded_position():
    assert [vara_id(1), vara_id(34), vara_id(123)] == ["v01", "v34", "v123"]


def test_behov_text_uses_decimal_comma():
    assert behov_text(item()) == "1,8 kg"
    assert behov_text(item(amount=3, unit="st")) == "3 st"
    assert behov_text(item(amount=None, unit=None)) == "okänt"


def test_item_matches_the_spec_shape():
    file, dropped = build_candidate_file("2026-09-28", 1, [Pending(item(), "v34", "högrev", [product(2737)])],
                                         now=NOW)
    assert list(file) == ["kandidat_id", "vecka", "omgång", "skapad", "batcher", "granskning"]
    assert file["vecka"] == "2026-09-28" and file["omgång"] == 1 and file["granskning"] is None
    assert file["skapad"] == "2026-09-24T21:10:00+02:00" and dropped == {}
    assert file["batcher"] == [{"batch": 1, "svarsfil": ".mathem-matchning/omgang-1/batch-01.json", "varor": [
        {"vara_id": "v34", "vara": "Högrev", "behov": "1,8 kg", "kategori": "Kött & Fisk",
         "anteckning": "i bit; Galbi-jjim", "sökterm": "högrev",
         "kandidater": [{"produkt_id": 2737, "namn": "Scan Högrev Bit", "förpackning": "ca 1200 g",
                         "märkning": ["Kött från Sverige"]}]}]}]


def test_missing_note_is_empty_string():
    file, _ = build_candidate_file("w", 1, [Pending(item(note=None), "v01", "högrev", [])], now=NOW)
    assert file["batcher"][0]["varor"][0]["anteckning"] == ""


@pytest.mark.parametrize("n,sizes", [(0, []), (1, [1]), (12, [12]), (13, [7, 6]), (25, [9, 8, 8]),
                                     (68, [12, 12, 11, 11, 11, 11])])
def test_batches_hold_at_most_twelve_and_are_even(n, sizes):
    file, _ = build_candidate_file("w", 1, pending(n), now=NOW)
    assert [len(b["varor"]) for b in file["batcher"]] == sizes
    assert [b["batch"] for b in file["batcher"]] == list(range(1, len(sizes) + 1))
    assert [v["vara_id"] for b in file["batcher"] for v in b["varor"]] == [vara_id(i) for i in range(1, n + 1)]


def test_candidates_capped_at_twenty_in_given_order():
    file, dropped = build_candidate_file("w", 1, [Pending(item(), "v01", "högrev", [product(i) for i in range(1, 29)])],
                                         now=NOW)
    assert [c["produkt_id"] for c in file["batcher"][0]["varor"][0]["kandidater"]] == list(range(1, 21))
    assert dropped == {"v01": 8}


def test_no_price_or_deal_anywhere_in_the_file():
    review = [Review(Pending(item("Grädde"), "v09", "grädde", [product(5)]), [5], "fetthalt oklar")]
    file, _ = build_candidate_file("w", 2, pending(3, products=3), review, now=NOW)
    assert not [k for k in keys_of(file) if any(w in k for w in PRICE_WORDS)]
    text = json.dumps({k: v for k, v in file.items() if k != "kandidat_id"}, ensure_ascii=False)  # hex may hold digits
    for value in ("189", "157", "2 för 300", "210"):
        assert value not in text


def test_module_never_reads_prices():
    source = (Path(__file__).parents[1] / "mathem_cart" / "candidates.py").read_text(encoding="utf-8")
    for name in ("gross_price", "gross_unit_price", ".promotions", ".discount", "parse_pricing", "import pins"):
        assert name not in source


def test_kandidat_id_is_a_hash_of_the_content():
    a, _ = build_candidate_file("w", 1, pending(2), now=NOW)
    later, _ = build_candidate_file("w", 1, pending(2), now=NOW + timedelta(hours=1))
    other, _ = build_candidate_file("w", 1, pending(3), now=NOW)
    second, _ = build_candidate_file("w", 2, pending(2), now=NOW)
    assert len(a["kandidat_id"]) == 12 and int(a["kandidat_id"], 16) >= 0
    assert a["kandidat_id"] == later["kandidat_id"]          # skapad is not hashed
    assert len({a["kandidat_id"], other["kandidat_id"], second["kandidat_id"]}) == 3
    assert compute_kandidat_id(a) == a["kandidat_id"]


def test_round_two_review_part():
    review = [Review(Pending(item("Grädde"), "v12", "grädde", [product(4852)]), [4852], "fetthalt oklar")]
    file, _ = build_candidate_file("w", 2, [], review, now=NOW)
    assert file["batcher"] == []
    part = file["granskning"]
    assert part["svarsfil"] == ".mathem-matchning/omgang-2/granskning.json"
    assert part["varor"][0]["vara_id"] == "v12" and part["varor"][0]["kandidater"][0]["produkt_id"] == 4852
    assert part["varor"][0]["tidigare"] == {"beslut": "osäker", "godkända": [4852], "motivering": "fetthalt oklar"}


def test_item_without_candidates_is_kept():
    file, _ = build_candidate_file("w", 1, [Pending(item("Perillablad"), "v05", "perillablad", [])], now=NOW)
    assert file["batcher"][0]["varor"][0]["kandidater"] == []


def test_answer_paths():
    assert answer_path(1, 3) == ".mathem-matchning/omgang-1/batch-03.json"
    assert answer_path(2, "granskning") == ".mathem-matchning/omgang-2/granskning.json"


def test_write_and_read_round(tmp_path):
    file, _ = build_candidate_file("w", 1, pending(2), now=NOW)
    assert write_round(tmp_path, file) == tmp_path / CANDIDATE_FILE
    assert read_round(tmp_path) == file == read_round(tmp_path, 1)
    assert (tmp_path / MATCH_DIR / "omgang-1" / "kandidater.json").is_file()


def test_edited_file_is_rejected(tmp_path):
    file, _ = build_candidate_file("w", 1, pending(1), now=NOW)
    write_round(tmp_path, file)
    data = json.loads((tmp_path / CANDIDATE_FILE).read_text(encoding="utf-8"))
    data["batcher"][0]["varor"][0]["kandidater"].append(
        {"produkt_id": 666, "namn": "X", "förpackning": "", "märkning": []})
    (tmp_path / CANDIDATE_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CandidateFileError, match="ändrats"):
        read_round(tmp_path)


def test_missing_broken_or_wrong_round(tmp_path):
    with pytest.raises(CandidateFileError, match="kör plan"):
        read_round(tmp_path)
    (tmp_path / CANDIDATE_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(CandidateFileError):
        read_round(tmp_path)
    file, _ = build_candidate_file("w", 1, pending(1), now=NOW)
    write_round(tmp_path, file)
    with pytest.raises(CandidateFileError):
        read_round(tmp_path, 2)


def test_clear_matching(tmp_path):
    file, _ = build_candidate_file("w", 1, pending(1), now=NOW)
    write_round(tmp_path, file)
    (tmp_path / MATCH_DIR / "omgang-1" / "batch-01.json").write_text("{}", encoding="utf-8")
    clear_matching(tmp_path)
    assert not (tmp_path / CANDIDATE_FILE).exists() and not (tmp_path / MATCH_DIR).exists()
    clear_matching(tmp_path)   # idempotent


def test_each_part_is_also_written_on_its_own(tmp_path):
    review = [Review(Pending(item("Grädde"), "v30", "grädde", [product(5)]), [5], "fetthalt oklar")]
    file, _ = build_candidate_file("w", 2, pending(13, products=15), review, now=NOW)
    write_round(tmp_path, file)
    assert part_path(2, 1) == ".mathem-matchning/omgang-2/batch-01-kandidater.json"
    assert part_path(2, "granskning") == ".mathem-matchning/omgang-2/granskning-kandidater.json"
    for pid, part in [(1, file["batcher"][0]), (2, file["batcher"][1]), ("granskning", file["granskning"])]:
        on_its_own = json.loads((tmp_path / part_path(2, pid)).read_text(encoding="utf-8"))
        assert on_its_own == {"kandidat_id": file["kandidat_id"], "vecka": "w", "omgång": 2, "batch": pid,
                              "svarsfil": part["svarsfil"], "varor": part["varor"]}


def test_a_full_batch_fits_one_read(tmp_path):
    long = "Garant Ekologisk Svensk Vispgrädde Laktosfri 36% Extra Lång Produktbenämning"
    items = [Pending(item(f"Vara {i}"), vara_id(i), f"vara {i}",
                     [product(1000 * i + j, name=long, labels=("Från Sverige", "EKO", "Nyckelhålsmärkt"))
                      for j in range(15)]) for i in range(1, 13)]
    file, _ = build_candidate_file("w", 1, items, now=NOW)
    write_round(tmp_path, file)
    text = (tmp_path / part_path(1, 1)).read_text(encoding="utf-8")
    assert len(text) < 60_000 and text.count("\n") < 2000     # Read stops at ~25k tokens and 2000 lines


def test_frozen_digest_is_part_of_the_hash():
    plain, _ = build_candidate_file("w", 2, pending(1), now=NOW)
    frozen, _ = build_candidate_file("w", 2, pending(1), now=NOW, frozen="abc")
    assert "svar_omgång_1" not in plain and frozen["svar_omgång_1"] == "abc"
    assert plain["kandidat_id"] != frozen["kandidat_id"] == compute_kandidat_id(frozen)


def test_drop_warnings_name_a_few_items():
    items = pending(2)
    assert drop_warnings(items, {"v02": 8}) == [
        "1 vara hade fler än 20 kandidater efter reglerna (Vara 2 +8); agenterna ser de 15 första i Mathems "
        "ordning och upp till 5 till med lägst jämförpris"]
    assert drop_warnings(items, {}) == []


def test_drop_warnings_summarise_many_items_in_one_line():
    # Live run 2026-09-28: 64 of 68 items were capped, and one line each drowned the output.
    items = pending(8)
    warnings = drop_warnings(items, {vara_id(i): i for i in range(1, 9)})
    assert warnings == ["8 varor hade fler än 20 kandidater efter reglerna (36 bortkapade); "
                        "agenterna ser de 15 första i Mathems ordning och upp till 5 till med lägst jämförpris"]
