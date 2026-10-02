from mathem_cart.pins import load_pins


def test_missing_file_is_empty(tmp_path):
    pins = load_pins(tmp_path / "pins.yaml")
    assert pins.keys() == [] and pins.get("vispgrädde") is None


def test_round_trip_and_normalised_keys(tmp_path):
    path = tmp_path / "pins.yaml"
    pins = load_pins(path)
    pins.approve("Vispgrädde (verifiera)", 6851)
    pins.approve("vispgrädde", 2380)
    pins.approve("vispgrädde", 6851)          # no duplicates
    pins.set_fixed("Krossade tomater", 9876)
    pins.set_search("kycklingfilé", "kycklingbröstfilé")
    pins.save()
    again = load_pins(path)
    assert again.get("VISPGRÄDDE").approved == [6851, 2380]
    assert again.get("krossade tomater").fixed == 9876
    assert again.get("kycklingfilé").search == "kycklingbröstfilé"
    text = path.read_text(encoding="utf-8")
    assert "godkända:" in text and "fast: 9876" in text and "sök: kycklingbröstfilé" in text


def test_comments_survive_a_save(tmp_path):
    path = tmp_path / "pins.yaml"
    path.write_text("# min kommentar\nvispgrädde:\n  godkända: [6851]\n", encoding="utf-8")
    pins = load_pins(path)
    pins.approve("gul lök", 111)
    pins.save()
    assert path.read_text(encoding="utf-8").startswith("# min kommentar")


def test_comment_only_file_from_repo_keeps_header_and_block_style(tmp_path):
    path = tmp_path / "pins.yaml"
    path.write_text("# bara kommentar\n", encoding="utf-8")
    pins = load_pins(path)
    assert pins.keys() == []
    pins.approve("gul lök", 111)
    pins.save()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# bara kommentar") and "gul lök:\n" in text
