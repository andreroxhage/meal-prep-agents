from pathlib import Path

import pytest

from mathem_cart.shopping_list import load_shopping_list, parse_shopping_list

FIXTURE = Path(__file__).parent / "fixtures" / "handlingslista.md"


@pytest.fixture
def parsed():
    return load_shopping_list(FIXTURE)


def by_key(parsed, key):
    return next(i for i in parsed.items if i.key == key)


def test_categories_come_from_headings_without_emoji(parsed):
    assert by_key(parsed, "gul lök").category == "Grönsaker"
    assert by_key(parsed, "kycklingfilé").category == "Kött & Fisk"


@pytest.mark.parametrize("key,amount,unit", [
    ("gul lök", 3, "st"),
    ("potatis", 1.2, "kg"),          # decimal comma
    ("crème fraiche", 1.5, "dl"),    # decimal point + [x] checkbox
    ("vitlöksklyftor", 3, "st"),     # range -> upper bound
    ("dill", 0.5, "knippe"),         # unicode fraction
    ("jasminris", 1.5, "dl"),        # mixed number
    ("morötter", 500, "g"),          # no space before unit (Review Focus 2)
    ("krossade tomater", 800, "g"),  # 2 x 400 g (Review Focus 2)
    ("pasta", 2, "förp"),
    ("laxfilé", 600, "g"),           # "ca" prefix
    ("kycklingfilé", 1.2, "kg"),     # bold markers stripped
    ("kokosmjölk", 2, "burk"),       # plural unit (F3)
    ("tortillabröd", 1, "förp"),     # abbreviation with a period (F3)
])
def test_amounts_and_units(parsed, key, amount, unit):
    item = by_key(parsed, key)
    assert item.amount == pytest.approx(amount)
    assert item.unit == unit


def test_verifiera_is_a_flag_and_not_part_of_name(parsed):
    item = by_key(parsed, "vispgrädde")
    assert item.verify is True
    assert item.name == "vispgrädde"
    assert item.note is None


def test_other_parentheticals_and_comma_tail_become_note(parsed):
    assert by_key(parsed, "potatis").note == "fast"
    assert by_key(parsed, "laxfilé").note == "benfri"


def test_unparseable_amount_is_none(parsed):
    item = by_key(parsed, "chiliflakes efter smak")
    assert item.amount is None and item.unit is None


def test_skipped_sections_are_listed_as_excluded(parsed):
    assert parsed.excluded == ["Salt", "Svartpeppar", "Fisksås"]
    assert all(i.category not in ("Skafferi-antaganden (verifiera om du har hemma)", "Specialingredienser")
               for i in parsed.items)


def test_lines_before_first_heading_are_ignored():
    parsed = parse_shopping_list("- 1 st citron\n## Frukt\n- 2 st äpple\n")
    assert [i.key for i in parsed.items] == ["äpple"]


def test_number_without_unit_means_pieces():
    assert parse_shopping_list("## Frukt\n- 4 citroner\n").items[0].unit == "st"


def test_word_starting_with_unit_letters_is_not_a_unit():
    item = parse_shopping_list("## Grönsaker\n- 2 lök\n- 3 gurka\n").items
    assert [(i.amount, i.unit, i.key) for i in item] == [(2, "st", "lök"), (3, "st", "gurka")]


def test_line_numbers_and_raw_are_kept(parsed):
    item = by_key(parsed, "gul lök")
    assert item.raw == "- 3 st gul lök" and item.line_no == 6


def test_missing_file_names_the_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="03-handlingslista.md"):
        load_shopping_list(tmp_path / "03-handlingslista.md")


@pytest.mark.parametrize("line,amount,unit,key", [
    ("2 förp. pasta", 2, "förp", "pasta"),
    ("2 förpackningar pasta", 2, "förp", "pasta"),
    ("1 förpackning jäst", 1, "förp", "jäst"),
    ("2 burkar krossade tomater", 2, "burk", "krossade tomater"),
    ("2 knippen dill", 2, "knippe", "dill"),
    ("2 paket smör", 2, "paket", "smör"),
    ("2 msk. olja", 2, "msk", "olja"),
    ("1 tsk. salt", 1, "tsk", "salt"),
    ("3 st. citron", 3, "st", "citron"),
    ("500 g. mjöl", 500, "g", "mjöl"),
])
def test_plural_and_abbreviated_units(line, amount, unit, key):
    # F3: these used to become "st" with the unit word left in the name (and pin key).
    item = parse_shopping_list(f"## Skafferi\n- {line}\n").items[0]
    assert (item.amount, item.unit, item.key) == (amount, unit, key)


def test_unit_prefix_of_a_word_is_still_not_a_unit():
    items = parse_shopping_list("## Grönsaker\n- 2 burkarsallad\n- 1 stjärnanis\n").items
    assert [(i.unit, i.key) for i in items] == [("st", "burkarsallad"), ("st", "stjärnanis")]


# --- Table format (live lists from 2026-08 use tables, not bullets) ---

TABLE = Path(__file__).parent / "fixtures" / "handlingslista-tabell.md"


@pytest.fixture
def table():
    return load_shopping_list(TABLE)


@pytest.mark.parametrize("key,amount,unit,category", [
    ("gul lök", 6, "st", "Grönsaker"),
    ("vitlök", 3, "st", "Grönsaker"),          # "3 hela"
    ("morot", 500, "g", "Grönsaker"),
    ("salladshuvud", 2, "st", "Grönsaker"),
    ("färsk mynta", 1, "kruka", "Grönsaker"),
    ("bladpersilja", 2, "knippe", "Grönsaker"),
    ("citrongräs", 4, "st", "Grönsaker"),      # "4 stjälkar"
    ("torskrygg", 1.2, "kg", "Kött & Fisk"),   # first of "Torskrygg / torskfilé"
    ("mjölk", 1, "dl", "Mejeri & Ägg"),
    ("parmesan", 150, "g", "Mejeri & Ägg"),    # "150 g bit"
    ("fiskfond", 1, "l", "Skafferi"),          # "till 1 l"
    ("torrt vitt vin", 1, "flaska", "Skafferi"),
    ("rårörda lingon", 1, "burk", "Skafferi"), # "1 burk/paket"
    ("surdegsbröd", 1, "limpa", "Skafferi"),
])
def test_table_rows(table, key, amount, unit, category):
    item = by_key(table, key)
    assert (item.amount, item.unit, item.category) == (pytest.approx(amount), unit, category)


def test_table_notes_come_from_note_column_and_leftovers(table):
    assert by_key(table, "gul lök").note == "ca 700 g; Huvuddelen till den brynta löken"
    assert by_key(table, "torskrygg").note == "torskfilé; Fryst är helt rätt här och billigast"
    assert by_key(table, "salladshuvud").note == "smörsallad"
    assert by_key(table, "böngroddar").note == "Valfritt"
    assert by_key(table, "parmesan").note == "bit; Riv själv"


def test_table_dish_reference_column_is_not_a_note(table):
    assert "[1]" not in (by_key(table, "rårörda lingon").note or "")


def test_table_verifiera_in_note_sets_flag(table):
    assert by_key(table, "mjölk").verify is True


def test_table_row_without_amount_is_kept_without_amount(table):
    item = by_key(table, "ägg")
    assert item.amount is None and item.unit is None


def test_only_shopping_items_are_parsed(table):
    assert len(table.items) == 16
    keys = {i.key for i in table.items}
    assert not keys & {"punkt", "mjölk & ströbröd", "grädde", "torsk", "jasminris", "potatis"}


def test_pantry_and_already_bought_sections_are_excluded(table):
    assert table.excluded == ["Salt", "svartpeppar", "Socker", "Jasminris"]


@pytest.mark.parametrize("line,amount,unit", [
    ("- 2 krukor basilika", 2, "kruka"),
    ("- 2 flaskor vin", 2, "flaska"),
    ("- 1 påse spenat", 1, "påse"),
    ("- 1 hel vitlök", 1, "st"),
])
def test_package_words_in_bullets(line, amount, unit):
    item = parse_shopping_list(f"## Övrigt\n{line}\n").items[0]
    assert (item.amount, item.unit) == (amount, unit)


# --- Name-first bullets ("- [ ] Vara — mängd (not)"), Notion export 2026-09-24 ---

NAME_FIRST = Path(__file__).parent / "fixtures" / "handlingslista-namn-forst.md"


@pytest.fixture
def name_first():
    return load_shopping_list(NAME_FIRST)


@pytest.mark.parametrize("key,amount,unit", [
    ("gul lök", 9, "st"),
    ("vitlök", 3, "st"),            # "3 hela vitlökar"
    ("tomater", 500, "g"),
    ("vitkål", 700, "g"),           # "700 g / ½ huvud"
    ("babyspenat", 1, "påse"),
    ("perillablad", 10, "st"),      # "8–10 blad"
    ("koriander", 2, "kruka"),
    ("smör", 1, "paket"),
    ("cheddar", 400, "g"),          # "Cheddar, lagrad, i block"
    ("högrev", 1.8, "kg"),
    ("majs", 2, "burk"),
    ("tomatpuré", 1, "tub"),
    ("farinsocker", 1, "förp"),     # "minsta påsen"
    ("honung", 1, "burk"),          # "1 liten burk"
    ("paprikapulver", 2, "msk"),
    ("sesamolja", 1, "flaska"),     # "1 liten flaska"
])
def test_name_first_bullets(name_first, key, amount, unit):
    item = by_key(name_first, key)
    assert (item.amount, item.unit) == (pytest.approx(amount), unit)


def test_name_first_notes_and_verify(name_first):
    assert by_key(name_first, "cheddar").note.startswith("lagrad, i block")
    assert by_key(name_first, "perillablad").verify is True
    assert by_key(name_first, "tomater").note.startswith("plommon- eller kvisttomater")


def test_at_home_subsection_and_check_at_home_section_are_excluded(name_first):
    keys = {i.key for i in name_first.items}
    assert not keys & {"blandfärs", "laxfilé", "salt och flingsalt", "rapsolja"}
    assert name_first.excluded == ["Blandfärs", "Laxfilé", "Salt och flingsalt", "Rapsolja / neutral olja",
                                   "Gochugaru"]


def test_commentary_sections_are_ignored(name_first):
    assert not any(i.key.startswith("högrev 1,8") for i in name_first.items)
    assert len(name_first.items) == 16


def test_subsection_ends_at_next_heading():
    parsed = parse_shopping_list("## Kött & Fisk\n### Finns hemma — köp inte\n- Blandfärs — 1 kg\n"
                                 "## Skafferi\n- Ris — 1 kg\n")
    assert [i.key for i in parsed.items] == ["ris"]


def test_special_ingredient_notes_for_listed_items_are_not_excluded():
    # "Specialingredienser att verifiera" annotates items that are also in the main list.
    parsed = parse_shopping_list(
        "## Grönsaker\n- [ ] Perillablad — 8–10 blad\n## Skafferi\n- [ ] Kastanjer, förkokta — 200 g\n"
        "- [ ] Gochugaru (koreanskt chilipulver) — 2 msk\n"
        "## Specialingredienser att verifiera\n- **Gochugaru** — asiatisk butik.\n"
        "- **Perilla** — valfritt.\n- **Förkokta kastanjer** — delikatessdisk.\n- **Yuzu** — asiatisk butik.\n")
    assert [i.key for i in parsed.items] == ["perillablad", "kastanjer", "gochugaru"]
    assert parsed.excluded == ["Yuzu"]
