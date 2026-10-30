"""CleanListen and CleanRead offer the same filters (Lauren, 2026-10-30), religion comes in parts,
and Jesus or Christ said with reverence isn't muted as a swear (Jason, 2026-10-30)."""
import re
from pathlib import Path

import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
from conftest import words

ROOT = Path(__file__).resolve().parents[1]


def option_keys(path):
    """The tick boxes and choices on a setup page, read from its source."""
    src = (ROOT / path).read_text(encoding="utf8")
    keys = set(re.findall(r'\("([a-z_]+)", "[A-Z][^"]*", (?:True|False)', src))
    keys |= set(re.findall(r'\("([a-z_]+)", "[A-Z][^"]*", \d, \d, \d\)', src))     # kids' boxes
    keys |= set(re.findall(r'self\.opts\["([a-z]+)"\] = ', src))
    if "KID_OPTS = [" in src:                                                    # CleanRead's
        keys |= set(re.findall(r'\("([a-z]+)", "[A-Z]', src.split("KID_OPTS = [", 1)[1].split("]", 1)[0]))
    if "KISS_CHOICES" in src or "KISS = [" in src:
        keys.add("kiss")
    if "RELIGION_LABELS" in src:
        keys |= {"religion_" + p for p in E.RELIGION_PARTS}
    return keys - {"religion_strict"}


def test_both_apps_offer_the_same_filters():
    listen, read = option_keys("CleanListen.pyw"), option_keys("CleanRead.pyw")
    assert listen == read, (sorted(listen - read), sorted(read - listen))
    assert {"rude", "sleeping", "substances", "kiss", "religion_prayers"} <= listen


def test_every_passage_filter_has_rules_for_claude():
    assert set(cc.KIND_RULES) == set(E.AI_TYPES)
    assert set(cc.KIND_NAMES) - {"added"} == set(E.AI_TYPES)


@pytest.mark.parametrize("text", [
    "children who needed to hear of Jesus.", "build a house on the cornerstone of Christ",
    "a man should love his wife as Christ loved the church.", "the saving grace of the Lord Jesus.",
    "Sobs tore through my body. Please, Jesus. Please.", "Jesus told us to be as wise as serpents",
    "convey the love of Christ to my parents", "the gospel of Jesus Christ.", "Christ is risen!",
    "And thank You, Jesus.", "love for my Jesus and love for my grandmother."])
def test_his_name_said_with_reverence_is_not_muted(text):
    assert E.find_language(words(text), ["deity"]) == []


@pytest.mark.parametrize("text", [
    "Jesus! You scared me.", "Jesus, is that you?", "Christ, that hurt.", "Jesus Christ, what a mess.",
    "Oh my Jesus, look at that.", "For the love of Christ, shut up.", "Sweet Jesus.",
    "God help him if he's late.", "By Allah, it's true"])
def test_his_name_as_an_oath_is_still_muted(text):
    assert E.find_language(words(text), ["deity"])


def test_religion_comes_in_parts():
    assert "NOT this" in E.religion_def() and "a prayer" not in E.religion_def()
    assert "a prayer" in E.religion_def(("preach", "anger", "prayers"))
    assert "preaching or explaining beliefs is NOT this" in E.religion_def(("anger",))
    rule = cc.religion_rule({"religion_parts": ["anger"]})
    assert "turned OFF preaching" in rule and "turned OFF anger" not in rule
    assert cc.religion_rule({"strict_religion": True}) == cc.STRICT_RELIGION_RULE
    assert cc.religion_rule({}) == cc.KIND_RULES["religion"]
    assert R.religion_parts({"religion": True}) == {"preach", "anger"}
    assert R.religion_parts({"religion": True, "religion_strict": True}) == set(E.RELIGION_PARTS)
    assert R.religion_parts({"religion": False, "religion_prayers": True}) == set()


BOOK = """Chapter One

"Please, God, keep him safe tonight," she prayed quietly before bed.

"I hate God for taking her," he shouted at the empty sky.

Sam called his brother a stupid idiot and ran off laughing.

They shared a bottle of whiskey and got drunk behind the barn.
"""


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def _cut(an, text):
    return any(text in c["raw"] for c in an["cuts"])


def test_cleanread_religion_parts_and_new_filters(book):
    base = {"religion": True, "kiss": "keep"}
    an = R.analyze(book, base)
    assert _cut(an, "I hate God") and not _cut(an, "keep him safe")
    an = R.analyze(book, dict(base, religion_anger=False, religion_prayers=True))
    assert _cut(an, "keep him safe") and not _cut(an, "I hate God")
    an = R.analyze(book, {"rude": True, "substances": True, "kiss": "keep"})
    assert {m["word_raw"].lower() for m in an["mutes"]} >= {"stupid", "idiot"}
    assert _cut(an, "whiskey")


def test_cleanlisten_reads_the_same_word_lists_as_cleanread():
    assert E.sleeping_hit(words("They had an affair that summer."))
    assert E.substances_hit(words("He got drunk on whiskey."))
    assert E.kiss_hit(words("She kissed him."), "all") and not E.kiss_hit(words("She kissed him."), "passionate")
    assert not E.kiss_hit(words("Mom kissed her little girl goodnight."), "all")


def test_exclamations_and_idioms_are_not_religious_talk():
    # CleanView 1.18.5: "Thank God", "a match made in heaven" muted whole lines as religion
    assert "a match made in heaven" in E.religion_def() and "'Thank God'" in E.religion_def()
    assert "'Thank God'" not in E.religion_def(("preach", "anger", "prayers"))
    assert "a match made in heaven" in cc.KIND_RULES["religion"]
    assert "a match made in heaven" in cc.STRICT_RELIGION_RULE
