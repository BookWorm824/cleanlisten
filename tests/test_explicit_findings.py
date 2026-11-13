"""Explicit findings in coroner, doctor and detective talk (the owner, 2026-11-13: "any explicit talk
should be removed from coroner talk regardless of medical /coroner - tearing, vaginal bruising etc";
how: "whole line on sexual reference , just the word on Sexual words"). Plain case talk ("any signs
of sexual assault?") still follows Medical. With sexual references ticked the line stays cut whatever
an AI or Claude says; her own choice still wins."""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc
import cleanread as R
from conftest import make_book, words

LINES = ["The rain fell all night.", "The coroner found vaginal bruising and tearing.",
         "Any signs of sexual assault?", "There was tearing.",
         "Tearing consistent with forced penetration.", "She tore the letter, tearing it to bits.",
         "He came tearing down the road after the assault on the fort.",
         "Bruising on her arms and neck.", "They drove home."]
EXPLICIT = [LINES[1], LINES[3], LINES[4]]


@pytest.mark.parametrize("line", ["The coroner found vaginal bruising.", "Anal tearing, the doctor said.",
                                  "Signs of penetration were found.", "Bruising of the labia.",
                                  "She was raped; there was tearing."])
def test_explicit_words(line):
    assert E.find_language(words(line), ["sexual"])


@pytest.mark.parametrize("line", ["She was tearing up the letter.", "Tearing it open, he laughed.",
                                  "The bullet penetrated his lung.", "Bruising on her arms and neck.",
                                  "Any signs of sexual assault?", "He came tearing down the road.",
                                  "An analysis of the canal."])
def test_not_explicit(line):
    assert not E.find_language(words(line), ["sexual"])


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("\n\n".join(LINES), encoding="utf8")
    return R.Book(str(p))


def cut_lines(an):
    return [c.get("raw", c["text"]) for c in an["cuts"] if c["cut"]]


def test_cleanread_whole_line_with_sexual_references_medical_off(book):
    an = R.analyze(book, {"refs": True, "medical": False})
    assert cut_lines(an) == EXPLICIT and all(c["kind"] == "ref" for c in an["cuts"])


def test_cleanread_just_the_word_with_only_sexual_words(book):
    an = R.analyze(book, {"sexual": True, "medical": False})
    assert not an["cuts"]
    assert [m["word_raw"].lower() for m in an["mutes"] if m["on"]] == [
        "vaginal", "tearing", "tearing", "tearing", "forced penetration"]


def test_cleanread_nothing_with_neither(book):
    an = R.analyze(book, {"medical": True})
    assert not an["mutes"] and not any(c["kind"] == "ref" for c in an["cuts"])


def test_cleanread_an_ai_cant_keep_it_but_you_can(book, monkeypatch):
    class AI:
        MODEL = "fake:explicit"

        def ensure_ai(self, progress=None):
            pass

        def chat(self, prompt, schema=None, timeout=300):
            return {"flags": [], "fits": False, "sexual": False, "fine": [], "confidence": "low"}
    monkeypatch.setattr(R, "_ai", lambda: AI())
    an = R.analyze(book, {"refs": True, "medical": False, "ai": True})
    assert cut_lines(an) == EXPLICIT                      # the AI said "doesn't fit" to every one
    key = next(c["key"] for c in an["cuts"] if c.get("raw", c["text"]) == LINES[3])
    monkeypatch.setattr(R, "fine_keys", lambda shared=True: {"ref": {key}})
    again = R.analyze(book, {"refs": True, "medical": False})
    assert LINES[3] not in cut_lines(again)               # what you kept before stays your call


def test_cleanread_content_check_lists_them(book):
    refs = [it["text"] for it in R.scan(book)["cats"]["ref"]["items"]]
    assert len(refs) == 3


def test_cleanlisten_passages_stay_cut():
    asr, sents = make_book(LINES)
    spans = {i: E.span_times(asr, a, b) for i, (a, b) in enumerate(sents)}

    def scene(i, cut, **kw):
        return dict({"kind": "ref", "part": 0, "s": spans[i][0], "e": spans[i][1], "cut": cut,
                     "text": LINES[i]}, **kw)
    st = {"mutes": [], "sentences": sents, "filters": {"kinds": ["ref"], "cats": []},
          "scenes": [scene(1, False, ai_note="AI thinks this one is fine"),
                     scene(3, False, by_you=True), scene(4, False, learned="you kept this before"),
                     scene(5, False)]}
    assert E.apply_explicit_findings(st, asr) == 1
    assert [sc["cut"] for sc in st["scenes"]] == [True, False, False, False]
    assert st["scenes"][0]["ai_note"] == E.EXPLICIT_NOTE
    st["filters"]["kinds"] = []                       # sexual references not ticked: nothing
    st["scenes"][0]["cut"] = False
    assert E.apply_explicit_findings(st, asr) == 0


def test_the_ai_and_claude_are_told():
    assert "vaginal" in E.AI_TYPES["ref"] and "IS this" in E.AI_TYPES["ref"]
    assert "vaginal" in cc.KIND_RULES["ref"]
