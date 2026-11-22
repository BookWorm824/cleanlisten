"""The same filters as CleanView (1.17.97; the owner, 2026-11-21, of the CleanView chat's list: "1,2,3,";
in CleanView Save: "CleanListen should have all your filters"): Coroner and doctor talk is its own box
(out of Medical), and a Drugs section has Drug talk and slang (the word muted, ticked for every age).
The Sexual words box stays (3)."""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
import filters as F


def words(text):
    return [E.norm(t) for t in text.split() if E.norm(t)]


def drug(text):
    ws = words(text)
    return [" ".join(ws[a:b]) for a, b, c in E.find_language(ws, ["drugtalk"]) if c == "drugtalk"]


@pytest.mark.parametrize("text, found", [
    ("He showed up stoned again.", "stoned"), ("Just another junkie.", "junkie"),
    ("They were getting high behind the gym.", "getting high"), ("He was shooting up heroin.", "shooting up"),
    ("A couple of crackheads.", "crackheads"), ("She was tripping balls.", "tripping balls"),
    ("He's strung out.", "strung out"), ("Some shrooms and a bong hit.", "shrooms"),
    ("She popped Percocet to get high.", "percocet"), ("Somebody slipped her roofies.", "roofies"),
])
def test_drug_talk_found(text, found):
    assert found in drug(text)


@pytest.mark.parametrize("text", [
    "They stoned him to death.", "He shall surely be stoned.", "A jar of stoned olives.",
    "An adrenaline junkie.", "He got high marks.", "The flames were shooting up.",
    "Prices are shooting up.", "Lights strung out along the road.", "The doctor prescribed Percocet.",
    "The Hindu Kush mountains.", "We've been jonesing for you.", "The police found cocaine.",
    "They smoked a joint of meat.",
])
def test_everyday_uses_stay(text):
    assert drug(text) == []


def test_the_drugs_section():
    heads = [h for h, _, _ in F.SECTIONS]
    assert "Drugs" in heads and "Smoking and drinking" in heads and "Smoking, drinking and drugs" not in heads
    assert [k for k, _, _ in F.SECTIONS[heads.index("Drugs")][2]] == ["drugs", "drugtalk"]
    for p in F.PRESETS:
        assert F.PRESETS[p]["drugtalk"] is True, p                  # ticked for every age
        assert "drugtalk" in F.groups(F.PRESETS[p])
    assert F.SECTION_ICONS["Drugs"] == "block"


def test_coroner_talk_has_its_own_box():
    med = [k for k, _, _ in F.SECTIONS[[h for h, _, _ in F.SECTIONS].index("Medical")][2]]
    assert med == ["medical", "forensic"]
    assert "forensic" in E.MORE_KINDS and "forensic" in E.AI_TYPES and "forensic" in cc.KIND_RULES
    assert "forensic" in F.listen_kwargs(dict(F.PRESETS["kids"]))["more"]
    assert "forensic" not in F.listen_kwargs(dict(F.PRESETS["adults"]))["more"]
    assert E.sentence_hit("forensic", words("Cause of death was blunt force trauma."))
    assert not E.sentence_hit("medical", words("Cause of death was blunt force trauma."))
    assert E.sentence_hit("medical", words("The nurse drew some blood."))


def test_saved_ticks_keep_what_they_did():
    assert F._upgrade({"medical": True})["forensic"] is True       # Medical had case talk in it
    assert F._upgrade({"medical": False})["forensic"] is False
    assert F._upgrade({"medical": True, "forensic": False})["forensic"] is False    # her own untick
    assert F._upgrade({"swearing": True})["drugtalk"] is True
    assert R._upgrade({"medical": True})["forensic"] is True and R._upgrade({})["drugtalk"] is True


def test_cleanread_mutes_drug_words(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("He came home stoned again and slept.\n\nThe stars were out.", encoding="utf8")
    book = R.Book(str(p))
    on = R.analyze(book, {"drugtalk": True})
    assert [m["cat"] for m in on["mutes"]] == ["drugtalk"]
    off = R.analyze(book, {"drugtalk": False})
    assert not off["mutes"]


def test_the_review_pages_know_them():
    listen = (E.Path(E.__file__).parent / "CleanListen.pyw").read_text(encoding="utf8")
    assert '("forensic", "Coroner and doctor talk to cut", "Coroner talk")' in listen
    assert '"drugtalk": "drug word"' in listen
    read = (E.Path(E.__file__).parent / "CleanRead.pyw").read_text(encoding="utf8")
    assert '"forensic",' in read
