"""The owner's hard rule (2026-11-13, every app): fart (crude humor), condom and semen (sexual
references) are always removed with their filter on: muted (marked out in a book) wherever they are
said, whatever an AI, Claude or a past choice said, and never learned as fine. Not farther,
farthing, condo, seaman. If she asks to leave one in, she's reminded it's a hard rule set on
13 November 2026; her own untick still works."""
import pytest

import cleanlisten as E
import cleanlisten_learn as L
import cleanread as R
from conftest import make_book, words


@pytest.mark.parametrize("line,kind", [
    ("He farted loudly.", "crude"), ("Farts are funny.", "crude"), ("Stop farting around.", "crude"),
    ("a box of condoms", "sexual"), ("We found a condom at the scene.", "sexual"),
    ("Semen was found on the sheet.", "sexual")])
def test_the_words(line, kind):
    assert [E.hard_rule_kind(w) for w in words(line) if E.hard_rule_kind(w)] == [kind]


@pytest.mark.parametrize("line", ["He walked farther.", "an old farthing", "a condo in Miami",
                                  "The seaman waved.", "seamen on deck"])
def test_not_the_lookalikes(line):
    assert not E.has_hard_rule_word(words(line))


# ---------- CleanRead ----------
TEXT = ["The wind blew across the fields.", "Benny farted and everyone laughed.",
        "They walked farther down the road.", "Detective Ryan found a condom in the car."]


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(TEXT), encoding="utf8")
    return R.Book(str(p))


def marked(an):
    return {m["word_raw"].lower(): (m["on"], m.get("note")) for m in an["mutes"]}


def test_cleanread_marks_them_out_with_their_filter(book):
    m = marked(R.analyze(book, {"crude": True, "refs": True}))
    assert m["farted"] == (True, E.HARD_RULE_NOTE) and m["condom"] == (True, E.HARD_RULE_NOTE)
    assert "farther" not in m


def test_cleanread_only_with_their_filter(book):
    assert not marked(R.analyze(book, {"crude": False, "refs": False, "sexual": False}))
    m = marked(R.analyze(book, {"sexual": True}))          # condom: the sexual words do it too
    assert "condom" in m and "farted" not in m


def test_cleanread_case_talk_keeps_the_word_muted(book):
    # Medical off leaves the detective's line alone, but the word itself still goes
    an = R.analyze(book, {"refs": True, "medical": False})
    assert marked(an)["condom"][0] is True
    assert not any("condom" in c["text"] for c in an["cuts"])


def test_cleanread_a_past_choice_doesnt_keep_them(book, monkeypatch):
    first = R.analyze(book, {"crude": True})
    key = next(m["key"] for m in first["mutes"] if m["word_raw"].lower() == "farted")
    monkeypatch.setattr(R, "fine_keys", lambda shared=True: {"word": {key}})
    assert marked(R.analyze(book, {"crude": True}))["farted"] == (True, E.HARD_RULE_NOTE)


def test_cleanread_never_learns_them_as_fine(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(R, "load_learned", lambda: {"fine": {}})
    monkeypatch.setattr(R, "save_learned", lambda d: saved.update(d))
    R.learn_marks([("crude", "k1", "Benny farted and everyone laughed.", True),
                   ("crude", "k2", "Benny burped at dinner.", True)])
    assert [e[0] for e in saved["fine"]["crude"]] == ["k2"]


# ---------- CleanListen ----------
def st_for(sentences, kinds=(), cats=()):
    asr, sents = make_book(sentences)
    return {"mutes": [], "scenes": [], "sentences": sents,
            "filters": {"kinds": list(kinds), "cats": list(cats)}}, asr


def test_cleanlisten_adds_and_reticks_them():
    st, asr = st_for(["Benny farted again.", "They found a condom.", "He walked farther."],
                     kinds=["crude", "ref"])
    i = next(k for k, w in enumerate(asr) if w["n"] == "condom")
    st["mutes"].append({"id": 1, "part": 0, "s": asr[i]["s"], "e": asr[i]["e"], "cat": "sexual",
                        "on": False, "note": "AI thinks this isn't swearing"})
    E.apply_hard_rule(st, asr)
    assert len(st["mutes"]) == 2                                   # condom ticked again, farted added
    assert all(m["on"] and m["note"] == E.HARD_RULE_NOTE for m in st["mutes"])
    assert {m["s"] for m in st["mutes"]} == {asr[i]["s"], next(w["s"] for w in asr if w["n"] == "farted")}


def test_cleanlisten_only_with_their_filter():
    st, asr = st_for(["Benny farted again.", "They found a condom."])
    E.apply_hard_rule(st, asr)
    assert st["mutes"] == []
    st["filters"]["cats"] = ["sexual"]
    E.apply_hard_rule(st, asr)
    assert len(st["mutes"]) == 1 and st["mutes"][0]["cat"] == "sexual"


def test_cleanlisten_never_learns_them_as_fine(monkeypatch):
    d = {"cut": [], "kept": [], "cut_for": {}, "kinds": {}, "words": {}, "word_mutes": [],
         "claude_cut": [], "claude_kept": [], "claude_ok_words": []}
    monkeypatch.setattr(L, "load", lambda: d)
    monkeypatch.setattr(L, "save", lambda x: None)
    st = {"scenes": [{"kind": "crude", "text": "Benny farted and everyone laughed at the table.",
                      "cut": False, "by_you": True},
                     {"kind": "crude", "text": "Benny burped and everyone laughed at the table.",
                      "cut": False, "by_you": True}],
          "mutes": [{"word": "condom", "word_raw": "condom", "on": False, "by_you": True}]}
    L.record(st)
    assert not any("farted" in s for s in d["kept"]) and any("burped" in s for s in d["kept"])
    assert "condom" not in d["words"]
    assert not L._may_be_fine("they found a condom")
