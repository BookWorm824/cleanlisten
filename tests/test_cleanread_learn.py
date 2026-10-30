"""CleanRead: what you mark "Not a problem" (content check) or untick (clean copy) is
remembered, re-applied only to what the same filter finds again, and sent in as one file."""
import json
import types

import pytest

import cleanread as R

BOOK = """Chapter One

Sam told his mom he hated her and slammed the door, then snuck out the window.

The witch cast a spell on the old oak tree and stirred her potion.

"What the hell is going on?" asked Dad. "Damn it, Sam, come back here."

Shut up, Sam.

Chapter Two

The wizard waved his wand and the lights went out.
"""
CLEAN = {"swearing": True, "mild": True, "deity": True, "sexual": True, "magic": True,
         "darkmagic": True, "kiss": "keep"}


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def _item(res, kind, text):
    return next(it for it in res["cats"][kind]["items"] if text in (it.get("raw") or it["text"]))


def test_marked_fine_is_left_out_next_time(book):
    res = R.scan(book)
    it = _item(res, "witchcraft", "cast a spell")
    assert res["cats"]["witchcraft"]["count"] == 1
    R.learn_marks([("witchcraft", it["key"], it["text"], True)])
    again = R.scan(book)
    assert again["cats"]["witchcraft"]["count"] == 0
    assert _item(again, "witchcraft", "cast a spell")["fine"]       # still there, to undo
    assert "Not a problem" in again["learn_note"]
    assert "cast a spell" not in R.report_html(again)


def test_undo_forgets_the_mark(book):
    it = _item(R.scan(book), "witchcraft", "cast a spell")
    R.learn_marks([("witchcraft", it["key"], it["text"], True)])
    R.learn_marks([("witchcraft", it["key"], it["text"], False)])
    assert R.scan(book)["cats"]["witchcraft"]["count"] == 1


def test_mark_only_applies_to_the_same_filter(book):
    it = _item(R.scan(book), "witchcraft", "cast a spell")
    R.learn_marks([("witchcraft", it["key"], it["text"], True)])
    cuts = R.analyze(book, CLEAN)["cuts"]
    witch = next(c for c in cuts if "cast a spell" in c["raw"])
    assert witch["kind"] == "magic" and witch["cut"]                 # "magic" wasn't marked


def test_kept_in_review_starts_unticked(book):
    an = R.analyze(book, CLEAN)
    c = next(c for c in an["cuts"] if "wizard" in c["raw"])
    R.learn_marks([(c["kind"], c["key"], c["raw"], True)])
    again = next(c for c in R.analyze(book, CLEAN)["cuts"] if "wizard" in c["raw"])
    assert not again["cut"] and again["ai_note"] == "You kept this before"


def test_word_kept_in_one_spot_only(book):
    res = R.scan(book)
    hell = next(it for it in res["lang"]["mild"]["items"] if it["word_raw"].lower() == "hell")
    R.learn_marks([("word", hell["key"], "x", True)])
    mutes = R.analyze(book, CLEAN)["mutes"]
    assert [m["on"] for m in mutes if m["word_raw"].lower() == "hell"] == [False]
    assert all(m["on"] for m in mutes if m["word_raw"].lower() == "damn")


def test_short_lines_are_not_reapplied(book):
    R.learn_marks([("rude_words", R.item_key("Shut up, Sam."), "Shut up, Sam.", True)])
    assert R.item_key("Shut up, Sam.") not in R.fine_keys().get("rude_words", set())


def test_export_has_every_find_and_the_marks(book, tmp_path):
    res = R.scan(book)
    it = _item(res, "witchcraft", "cast a spell")
    it["fine"] = True
    d = json.loads(R.export_marks(res, "check", tmp_path).read_text(encoding="utf8"))
    assert d["what"] == "CleanRead refined" and d["mode"] == "check"
    assert sum(x["not_a_problem"] for x in d["items"]) == 1
    an = R.analyze(book, CLEAN)
    an["cuts"][0]["cut"] = False
    path = R.export_marks(an, "clean", tmp_path)
    assert path.name.startswith("CleanRead refined - ")
    assert [x["removed"] for x in json.loads(path.read_text(encoding="utf8"))["items"]][0] is False


def test_ai_reading_checks_the_quoted_words(book, monkeypatch):
    """A find counts only if its quoted words are in that sentence (or the one next to it);
    past marks are shown to the AI as examples."""
    R.learn_marks([("rebellion", "a b c d e", "He told his mom he hated her.", True)])
    prompts = []

    def chat(prompt, schema=None, timeout=0):
        prompts.append(prompt)
        if "flags" in schema["properties"]:
            return {"flags": [{"n": 1, "type": "rebellion", "words": "slammed the door"},
                              {"n": 2, "type": "witchcraft", "words": "made up words"}]}
        return {"fits": True, "confidence": "high"}
    monkeypatch.setattr(R, "_ai", lambda: types.SimpleNamespace(ensure_ai=lambda p: None, chat=chat))
    found = R.ai_find(book, {"rebellion": "x", "witchcraft": "y"})
    assert [(book.sent_text(i)[:8], k) for i, k in found] == [("Sam told", "rebellion")]
    assert "He told his mom he hated her." in prompts[0]


def test_built_in_marks_from_sent_in_reports(book, tmp_path, monkeypatch):
    # families' clear wrong flags ship in shared_learned.json; your own marks still come first
    key = R.item_key("The witch cast a spell on the old oak tree and stirred her potion.")
    shared = tmp_path / "shared.json"
    shared.write_text(json.dumps({"cleanread_fine": {"witchcraft": [[key, "The witch cast a spell"]]}}),
                      encoding="utf8")
    monkeypatch.setattr(R, "SHARED", shared)
    assert R.scan(book)["cats"]["witchcraft"]["count"] == 0
    assert key not in R.fine_keys(shared=False).get("witchcraft", ())
    R.learn_marks([("magic", "something else entirely here today", "x", True)])
    assert [e[0] for e in R.all_fine()["witchcraft"]] == [key]
    assert "cleanread_fine" not in json.loads(R.LEARNED.read_text("utf8"))


def test_shipped_marks_are_well_formed():
    fine = R.shared_fine()
    assert fine and set(fine) <= set(R.CLEAN_AI)
    for kind, lst in fine.items():
        for key, text in lst:
            assert key == R.item_key(text) or R.item_key(text).startswith(key[:150]), (kind, text)
