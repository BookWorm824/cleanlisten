"""CleanRead's book check (Jason, 2026-11-03, "Wings of a Dream"): places in plain words, and
telling Claude what isn't a problem from the check page (marked and remembered like a click)."""
import pytest

import cleanlisten_claude as cc
import cleanlisten_learn as L
import cleanread as R

BOOK = """Chapter One

The witch cast a spell on the old oak tree and stirred her potion.

The witch flew away on her broomstick under the full moon.

The children laughed and ran down to the river after school.

Chapter Two

A ghost haunted the old house at the end of the lane, and nobody went there after dark.

"What the hell is going on?" asked Dad.
"""


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    monkeypatch.setattr(L, "PATH", tmp_path / "learned.json")
    monkeypatch.setattr(L, "APP_DATA", tmp_path)
    monkeypatch.setattr(L, "_shared", {"cut": [], "kept": [], "ok_words": [], "word_mutes": [],
                                       "cut_for": {}})
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def test_places_say_what_they_mean(book):
    assert book.where(0).startswith("Chapter One · ") and book.where(0).endswith("% of the way through the book")
    book.chapters = ["45"] * len(book.chapters)        # a book that names chapters with a number
    assert book.where(3).startswith("In “45” · ")
    book.chapters = []
    assert book.where(3)[0].isdigit() and "of the way through the book" in book.where(3)


def test_tell_claude_whats_not_a_problem_on_the_check_page(book, tmp_path, monkeypatch):
    r = R.scan(book)
    asked = []

    def run(prompt, system, schema=None, **kw):
        asked.append((prompt, system, schema))
        return {"session_id": "s", "data": {
            "answer": "Marked them.", "changes": [{"action": "fine", "id": "F1"},
                                                  {"action": "fine", "id": "F99"}],
            "remember": [{"note": "A witch in a fairy tale is fine.", "for": "this"}]}}
    monkeypatch.setattr(cc, "run", run)
    monkeypatch.setattr(cc, "saved_provider", lambda: "claude")
    chat = R.CheckChat(book, r, tmp_path / "chat")
    ans, changes, kept = chat.ask("The witches are fine")
    assert kept == [("A witch in a fairy tale is fine.", False)]
    # the check page's rules, then who does what (Jason, 2026-11-07)
    assert asked[0][1].startswith(R.CHECK_SYSTEM) and "You (Claude) are only this chat" in asked[0][1]
    assert asked[0][2] is R.CHECK_SCHEMA
    found = (tmp_path / "chat" / "findings.txt").read_text(encoding="utf8")
    assert found.startswith("F1 [found] ") and "of the way through the book" in found
    first = chat.items[0][2]
    done = chat.apply(changes)                         # F99 doesn't exist: skipped
    assert len(done) == 1 and first["fine"] is True
    # remembered like a "Not a problem" click: left out next time
    again = R.scan(book)
    kind = chat.items[0][0]
    pool = again["lang"] if kind == "word" else again["cats"]
    assert any(it.get("fine") for c in pool.values() for it in c["items"])
    chat.ask("thanks")
    assert "A witch in a fairy tale is fine." in asked[1][0]


def test_the_clean_chat_still_has_its_own_instructions(book, tmp_path, monkeypatch):
    an = R.analyze(book, {"magic": True})
    seen = []
    monkeypatch.setattr(cc, "run", lambda p, system, schema=None, **kw: seen.append((system, schema)) or
                        {"session_id": "s", "data": {"answer": "", "changes": [], "remember": []}})
    monkeypatch.setattr(cc, "saved_provider", lambda: "claude")
    R.Chat(book, an, tmp_path / "chat").ask("hi")
    assert "fine-tune what CleanRead takes out" in seen[0][0] and seen[0][1] is R.CHAT_SCHEMA
