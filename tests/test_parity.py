"""CleanListen and CleanRead offer the same filters (Lauren, 2026-10-30), religion comes in parts,
and Jesus or Christ said with reverence isn't muted as a swear (Jason, 2026-10-30)."""
import re
from pathlib import Path

import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
import filters as F
from conftest import words

ROOT = Path(__file__).resolve().parents[1]


def test_both_apps_use_the_shared_filters():
    # one list of boxes (filters.py) for CleanListen and CleanRead, so they can't drift apart
    for app in ("CleanListen.pyw", "CleanRead.pyw"):
        src = (ROOT / app).read_text(encoding="utf8")
        assert "import filters as F" in src and "F.FilterCard(" in src, app


def test_the_filters_are_cleanviews_for_books():
    cleanview = {"swearing", "mild", "deity", "minced", "samesexwords", "rude", "refs", "crude",
                 "bully", "disrespect", "religion", "nudity", "implied", "sex", "immodest",
                 "sleeping", "kiss", "kiss_ss", "relationships", "unmarried", "violence",
                 "graphic", "gore", "disturbing", "smoking", "drinking", "drugs", "gestures",
                 "holiday", "birthday", "darkmagic", "magic", "vampires"}
    assert cleanview <= set(F.STANDARD)
    assert [k for k, _ in F.PROFILES] == ["young", "kids", "teens", "adults"]
    # every passage filter the boxes turn on has a definition for the AI and rules for Claude
    t = dict(F.PRESETS["young"])
    on = set(F.listen_kwargs(t)["more"]) | {"kiss", "kiss_ss", "graphic", "gore", "sex", "ref"}
    assert on <= set(E.AI_TYPES) and on <= set(cc.KIND_RULES)


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
    an = R.analyze(book, {"rude": True, "drinking": True, "kiss": "keep"})
    assert {m["word_raw"].lower() for m in an["mutes"]} >= {"stupid", "idiot"}
    assert _cut(an, "whiskey")


def test_cleanlisten_reads_the_same_word_lists_as_cleanread():
    assert E.sleeping_hit(words("They had an affair that summer."))
    assert E.sentence_hit("drinking", words("He got drunk on whiskey."))
    assert not E.sentence_hit("smoking", words("He got drunk on whiskey."))
    assert E.kiss_hit(words("She kissed him."), "all") and not E.kiss_hit(words("She kissed him."), "passionate")
    assert not E.kiss_hit(words("Mom kissed her little girl goodnight."), "all")


def test_exclamations_and_idioms_are_not_religious_talk():
    # CleanView 1.18.5: "Thank God", "a match made in heaven" muted whole lines as religion
    assert "a match made in heaven" in E.religion_def() and "'Thank God'" in E.religion_def()
    assert "'Thank God'" not in E.religion_def(("preach", "anger", "prayers"))
    assert "a match made in heaven" in cc.KIND_RULES["religion"]
    assert "a match made in heaven" in cc.STRICT_RELIGION_RULE


def test_the_ai_looks_for_same_sex_content_but_only_ticks_what_the_lists_see(book, monkeypatch):
    # Lauren, 2026-10-30: "I still want it to look for those in books"; but the small AI once
    # ticked 56 ordinary man-and-woman lines of one romance
    found = {}

    def fake_find(bk, kinds, progress=None, cancel=None):
        found["kinds"] = set(kinds)
        return {(i, "relationship"): "high" for i, s in enumerate(bk.sents)
                if "barn" in bk.sent_text(i) or "brother" in bk.sent_text(i)}
    monkeypatch.setattr(R, "ai_find", fake_find)
    monkeypatch.setattr(R, "_ai", lambda: type("AI", (), {"chat": staticmethod(lambda *a, **k: {})})())
    an = R.analyze(book, {"relationships": True, "kiss": "keep", "ai": True})
    assert "relationship" in found["kinds"]
    ai = [c for c in an["cuts"] if c.get("ai")]
    assert ai and all(c["cut"] is False and c["ai_note"] == "AI suggests" for c in ai)
    assert E._ai_backed("relationship", words("He kissed his husband goodbye."))
    assert not E._ai_backed("relationship", words("He kissed his wife goodbye."))


@pytest.mark.parametrize("kind,text,hit", [
    ("violence", "He punched him and ran.", True), ("violence", "She owned a gun.", False),
    ("disturbing", "They tortured the prisoner for days.", True),
    ("nudity", "She was stark naked.", True), ("nudity", "He saw it with the naked eye.", True),
    ("implied", "He came out wrapped in a towel.", True),
    ("immodest", "She strutted past in a bikini.", True),
    ("gestures", "He flipped them off and drove away.", True),
    ("smoking", "He lit a cigarette.", True), ("drugs", "They smoked pot behind the gym.", True),
    ("unmarried", "They moved in together last spring.", True),
    ("unmarried", "Her mother and her sisters were living together.", False),
    ("sleeping", "They moved in together last spring.", False),
    ("sleeping", "He was having an affair.", True)])
def test_cleanviews_filters_for_books(kind, text, hit):
    assert E.sentence_hit(kind, words(text)) is hit


def test_gory_descriptions_come_in_two_levels():
    assert E.gore_level(words("Blood soaked his shirt from the wound.")) == "graphic"
    assert E.gore_level(words("His entrails spilled onto the floor.")) == "gore"


def test_kissing_is_man_and_woman_or_same_sex():
    assert E.kiss_hit(words("She kissed him."), "all") and not E.kiss_ss_hit(words("She kissed him."), "all")
    assert E.kiss_ss_hit(words("He kissed his boyfriend."), "all")
    assert not E.kiss_hit(words("He kissed his boyfriend."), "all")


def test_your_own_words_are_always_taken_out():
    mine = E.own_phrases(["grow some stones", "Dork"])
    hits = E.find_language(words("Grow some stones, you dork, said the milestones guy."), [], mine=mine)
    assert [(c, j - i) for i, j, c in hits] == [("mine", 3), ("mine", 1)]


def test_ages_remember_their_own_ticks(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", tmp_path / "none.json")
    d = F.load()
    assert d["profile"] == "adults" and F.ticks(d) == F.PRESETS["adults"]
    d["ticks"]["kids"] = {"violence": False}
    d["profile"] = "kids"
    F.save(d)
    d = F.load()
    assert F.ticks(d)["violence"] is False and F.ticks(d)["disturbing"] is True
    assert F.ticks(d, "adults")["violence"] is False and F.ticks(d, "young")["violence"] is True
    assert F.ticks(d, "teens")["magic"] is False and F.ticks(d, "kids")["kiss"] == "passionate"


def test_the_first_time_adults_start_from_cleanreads_old_ticks(tmp_path, monkeypatch):
    old = tmp_path / "cleanread_settings.json"
    old.write_text('{"mode": "clean", "kiss": "passionate", "substances": true, "gore": true}')
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", old)
    t = F.ticks(F.load())
    assert t["kiss"] == "passionate" and t["drinking"] and t["graphic"] and t["gore"]


def test_the_ticks_reach_both_engines():
    t = dict(F.PRESETS["adults"], violence=True, religion_prayers=True, kiss="passionate")
    kw = F.listen_kwargs(t, ["dork"])
    assert kw["more"] == ["violence"] and kw["religion_parts"] == ["preach", "anger", "prayers"]
    assert kw["kiss"] == "passionate" and kw["kiss_ss"] == "passionate" and kw["mine"] == [("dork",)]
    assert F.groups(t) == ["swearing", "mild", "deity", "sexual", "orientation"]
    assert F.read_opts(t, ["dork"])["mywords"] == ["dork"]
    assert "Taking out: Swearing" in F.summary(t) and "violence" in F.summary(t)
