"""Static checks of the two matcher agent definitions (matching spec §6, §12)."""

import json
import re
from pathlib import Path

import pytest
from ruamel.yaml import YAML

AGENTS = Path(__file__).resolve().parents[3] / ".claude" / "agents"
NAMES = {"mathem-matcher": "haiku", "mathem-granskare": "sonnet"}
REQUIREMENTS = """
1. Rätt vara är samma vara som på listan. **Inga varianter som listan inte ber om:**
   laktosfri, lätt, vegansk ersättning, smaksatt eller kryddad, färdigrätt, eller fel form
   (burgare är inte "högrev i bit", pulver är inte "vitlök").
2. Listans preciseringar är krav: "i bit", "benfri utan skinn", "lagrad, i block", "15 %".
3. Eko, märke och förpackningsstorlek är fria val. **Godkänn alla kandidater som duger** —
   koden väljer pris och storlek (storpack efter jämförpris för det som håller sig).
4. `vald` = minst en kandidat är tydligt rätt. `osäker` = en kandidat är rimlig men en
   precisering är oklar. `ingen_passar` = ingen duger; föreslå då en ny sökterm (bredare eller
   smalare) om en sådan sannolikt hjälper.
5. Använd bara id:n från varans egen kandidatlista. Svara på varje vara i batchen exakt en
   gång. Gissa aldrig om pris — du ser inga priser.
"""


def squash(text):
    return re.sub(r"\s+", " ", text).strip()


def parse(name):
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert match, f"{name}.md saknar frontmatter"
    fields = YAML(typ="safe").load(match.group(1))
    return fields, match.group(2)


def json_examples(body):
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", body, re.S)]


@pytest.mark.parametrize("name,model", NAMES.items())
def test_frontmatter(name, model):
    fields, _ = parse(name)
    assert fields["name"] == name and fields["model"] == model
    tools = fields["tools"]; assert set(tools if isinstance(tools, list) else [t.strip() for t in tools.split(",")]) == {"Read", "Write"}
    assert set(fields) == {"name", "description", "model", "tools", "hooks"}
    assert fields["description"]


@pytest.mark.parametrize("name", NAMES)
def test_requirements_verbatim(name):
    _, body = parse(name)
    assert squash(REQUIREMENTS) in squash(body)


@pytest.mark.parametrize("name,batch", [("mathem-matcher", 1), ("mathem-granskare", "granskning")])
def test_answer_example_has_the_contract_shape(name, batch):
    _, body = parse(name)
    answers = [e for e in json_examples(body) if "svar" in e]
    assert answers, "agenten saknar ett svarsexempel i ett ```json-block"
    for example in answers:
        assert list(example) == ["kandidat_id", "omgång", "batch", "svar"]
        assert type(example["omgång"]) is int and example["batch"] == batch
        for entry in example["svar"]:
            assert list(entry) == ["vara_id", "beslut", "godkända", "motivering", "ny_sökterm"]
            assert entry["beslut"] in ("vald", "osäker", "ingen_passar")
            assert all(type(i) is int for i in entry["godkända"]) and len(entry["motivering"]) <= 160
            if entry["beslut"] != "ingen_passar" or batch == "granskning":
                assert entry["ny_sökterm"] is None


def test_reviewer_rules():
    body = squash(parse("mathem-granskare")[1])
    assert "tidigare" in body and "granskning" in body
    assert "ny_sökterm" in body and "null" in body


@pytest.mark.parametrize("name", NAMES)
def test_agent_only_writes_its_answer_file(name):
    body = squash(parse(name)[1])
    assert "Svarsfil" in body and "exakt en gång" in body
    for forbidden in ("mathem-cart apply", "Bash", ".env"):
        assert forbidden not in body


SKILL = AGENTS.parent / "skills" / "mathem-cart" / "SKILL.md"


@pytest.mark.parametrize("name", NAMES)
def test_agent_reads_only_its_part_and_pages_if_needed(name):
    body = squash(parse(name)[1])
    assert "-kandidater.json" in body                       # its own part file, not the whole round
    assert "offset" in body and "limit" in body


def test_matcher_never_proposes_a_term_in_round_two():
    body = squash(parse("mathem-matcher")[1])
    assert "Bara i omgång 1. Är `omgång` 2 är `ny_sökterm` alltid `null`" in body
    assert "`ny_sökterm`: en sträng bara vid `ingen_passar` i omgång 1, annars `null`." in body


@pytest.mark.parametrize("name", NAMES)
def test_a_fallback_in_the_note_is_a_reserve(name):
    body = squash(parse(name)[1])
    assert 'Står det "annars X" i `anteckning` är X en reserv' in body
    assert "Finns bara reserven: svara `vald` med reserven i `godkända`" in body
    assert "osäker` med reserven" not in body


@pytest.mark.parametrize("name", NAMES)
def test_a_blend_is_not_the_item(name):
    body = squash(parse(name)[1])
    assert '"Smör & Raps" (Bregott) är inte smör' in body and '"Sesamolja med Sojabönolja" är inte sesamolja' in body


def test_skill_never_dispatches_the_agents_as_general_purpose():
    text = squash(SKILL.read_text(encoding="utf-8"))
    assert "skicka ut `general-purpose`" not in text
    assert "Skicka inte ut någon annan agenttyp" in text


def test_skill_does_not_read_the_whole_candidate_file():
    text = squash(SKILL.read_text(encoding="utf-8"))
    assert "Läs `<vecka>/06-mathem-kandidater.json` med Read" not in text
    assert "Läs inte `06-mathem-kandidater.json`" in text
