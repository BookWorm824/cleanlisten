""""AI" instead of Claude, ChatGPT or Gemini, everywhere but where one is chosen and set up (1.17.34,
as CleanView 1.18.86; the owner, 2026-11-13, there: "Not in the Claud, chat, gemini section, but
everywhere else in clean view, instead of saying "claude" say "Ai""; asked about the book apps:
"yes"). Which one helped is still kept with the book; only what's shown changed."""
import importlib.machinery
import importlib.util
import re
import types

import pytest

import cleanlisten as E
import cleanlisten_claude as cc
from conftest import REPO

NAMES = ("Claude", "ChatGPT", "Gemini")


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("old, new", [
    ("Claude: fine", "AI: fine"), ("ChatGPT: trimmed", "AI: trimmed"),
    ("Gemini: just the word", "AI: just the word"), ("Claude agrees", "AI agrees"),
    ("Claude unsure", "AI unsure"), ("ChatGPT suggests", "AI suggests"),
    ("Found by Claude", "Found by AI"), ("Claude chat", "AI chat"),
    ("Claude chat: trimmed", "AI chat: trimmed"),
    ("Your call (Claude differs)", "Your call (the AI differs)"),
    ("Muted (Gemini questioned it)", "Muted (the AI questioned it)"),
    ("Claude read the whole book: agreed with 12, unticked 3 it says aren't an issue. 2 it wasn't "
     "sure about are marked “Claude unsure”.",
     "The AI read the whole book: agreed with 12, unticked 3 it says aren't an issue. 2 it wasn't "
     "sure about are marked “AI unsure”."),
    ("ChatGPT couldn't check this book (no internet). The results below are from the word lists.",
     "The AI couldn't check this book (no internet). The results below are from the word lists.")])
def test_a_note_from_a_book_checked_before_is_shown_the_new_way(old, new):
    assert E.plain_ai(old) == new
    assert E.plain_ai(new) == new                   # and a new one is left as it is


@pytest.mark.parametrize("note", ["AI agrees", "found by AI", "AI on this PC suggests",
                                  "Learned: fine", "Your own words", "Added by you",
                                  "always removed (your hard rule, set 13 November 2026)", ""])
def test_other_notes_are_left_alone(note):
    assert E.plain_ai(note) == note
    assert E.plain_ai(None) == ""


def test_the_engines_new_notes_and_progress_say_ai():
    src = (REPO / "cleanlisten_claude.py").read_text(encoding="utf8")
    review = src[src.index("def apply_review("):src.index("class ", src.index("def review("))]
    # (only the message that sends you to set it up names it, and the record of which one helped)
    assert review.count("name()") == 2 and "isn't set up or signed in yet" in review
    assert 'st["reviewer"] = name()' in review
    assert 'f"{E.THE_AI} is reading the book · section' in src
    assert 'f"{E.THE_AI} read the whole book: agreed with' in src
    assert src.count('f"{E.AI} chat') == 6 and 'f"{name()} chat' not in src
    # signing in and the plan's limit are about the one chosen: they name it
    assert 'f"{name()} isn\'t signed in.' in src and 'f"Your {name()} usage limit was reached.' in src
    eng = (REPO / "cleanlisten.py").read_text(encoding="utf8")
    assert 'f"{THE_AI} couldn\'t check this book' in eng


def test_which_one_helped_is_still_kept():
    src = (REPO / "cleanlisten_claude.py").read_text(encoding="utf8")
    assert re.search(r'st\["reviewer"\]\s*=\s*name\(\)', src)
    assert E.AI == "AI" and E.THE_AI == "The AI" and cc.name("chatgpt") == "ChatGPT"


def test_cleanlistens_window_says_ai_and_names_it_only_for_setting_up():
    m = load("say_ai_cleanlisten", "CleanListen.pyw")
    me = types.SimpleNamespace(_cc=lambda: types.SimpleNamespace(name=lambda: "ChatGPT"))
    assert m.App._ai_name(me) == "AI" and m.App._provider(me) == "ChatGPT"
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    for said in ('"The AI is checking the book\\u2026"', 'text=f"Ask {N}…"',
                 '"Undo the AI\'s last change"', '"Open the AI\'s findings for this book (spreadsheet)"',
                 'f"Ask {N} about this…"', '"The AI is reading the book\\u2026"',
                 '"The AI can read the whole book', '"Tip: the AI looks over the whole book',
                 'engine.AI + ": " + sc["claude_reason"]', 'messagebox.showerror("AI check"',
                 'engine.plain_ai(sc["ai_note"])', 'engine.plain_ai(m["note"])',
                 'engine.plain_ai(a.get("claude_note"))'):
        assert said in src, said
    # where one is chosen and set up, and the messages that send you there, still name them
    for kept in ('"Final check by Claude, ChatGPT or Gemini  (reads the whole book)"',
                 '[("claude", "Claude"), ("chatgpt", "ChatGPT"), ("gemini", "Gemini")]',
                 'f"{self._provider()} isn\'t set up or signed "', 'f"\\u2713 {N} is ready"',
                 '"Save a list of everything for Claude…"',          # her chat with us
                 '"Claude model:"',
                 # the check button names it again (the owner, 2026-11-14: "check with ai sounds
                 # like what we already did"; tests/test_check_with_ai.py)
                 'f"Check again with {self._provider()}"', 'else f"Check with {self._provider()}"'):
        assert kept in src, kept
    # nothing shown names one any more outside those
    assert 'a.get("reviewer", "Claude") + ": "' not in src
    assert "Claude is reading the whole book" not in src and '"Claude check"' not in src


def test_cleanreads_window_says_ai():
    m = load("say_ai_cleanread", "CleanRead.pyw")
    assert m.App._ai_name(types.SimpleNamespace()) == "AI"
    src = (REPO / "CleanRead.pyw").read_text(encoding="utf8")
    for said in ('f"Ask {self._ai_name()}…"', 'w.title(f"Ask {self._ai_name()} about this book")',
                 '"The AI reads the whole book and everything CleanRead found.',
                 '"Tip: the AI looks over the whole book', '"The AI is reading the book…"'):
        assert said in src, said
    assert 'f"press “Sign in to {N}” once, then come back here."' in src      # sends you there
    assert not re.search(r'f"\{N\} (reads|looks)', src)


def test_a_review_note_made_now_says_ai(monkeypatch):
    """apply_review with ChatGPT chosen: the labels say AI."""
    monkeypatch.setattr(cc, "PROVIDER", "chatgpt")
    st = {"scenes": [{"id": 1, "kind": "ref", "part": 0, "s": 0.0, "e": 1.0, "cut": True,
                      "text": "A line."}], "mutes": [], "filters": {"cats": []}}
    counts = {"agree": 0, "off": 0, "unsure": 0, "on": 0, "found": 0, "suggested": 0, "word": 0,
              "trim": 0}
    cc.apply_review(st, {"decisions": [{"id": "P1", "verdict": "keep", "confidence": "high",
                                        "reason": "not about that"}]}, counts)
    assert st["scenes"][0]["ai_note"] == "AI: fine" and st["scenes"][0]["cut"] is False
    assert not any(n in st["scenes"][0]["ai_note"] for n in NAMES)
