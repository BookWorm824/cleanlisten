"""A swear is never spelled out on CleanListen's screens (the owner, 2026-11-25, of CleanView: "I
NEVER want to see the words spelled out!! the whole point is not see it"): the AI's notes and
reasons, its chat answers, a passage's text and the heads-up are starred; only "Show" writes a
word out."""
from pathlib import Path

import pytest

import cleanlisten as E

CASES = [
    ('Mute just the word "damn": it is the only problem.', 'Mute just the word "d***": it is the only problem.'),
    ("What the hell, he said.", "What the h***, he said."),
    ("She’s a son of a bitch.", "She’s a son of a b****."),
    ("Oh my God, she cried.", "Oh my G**, she cried."),
    ("He said shit-faced.", "He said s***-faced."),
    ("Go screw yourself.", "Go s**** yourself."),
]


@pytest.mark.parametrize("text,want", CASES)
def test_swears_are_starred_and_the_rest_kept(text, want):
    assert E.hide_words(text) == want


@pytest.mark.parametrize("text", ["Nothing bad here, Gruffi.", "Thank God you came.", "", "  ", "12:30 · 4 sec"])
def test_clean_text_is_left_alone(text):
    assert E.hide_words(text) == text


def test_none_is_empty():
    assert E.hide_words(None) == ""


SRC = (Path(__file__).resolve().parent.parent / "CleanListen.pyw").read_text(encoding="utf8")


@pytest.mark.parametrize("shown", [
    'engine.hide_words(sc["text"])', 'engine.hide_words(sc["claude_reason"])',
    'engine.hide_words(sc["chat_answer"])', 'engine.hide_words(engine.plain_ai(sc["ai_note"]))',
    'engine.hide_words(engine.plain_ai(m["note"]))', 'engine.hide_words(h["text"])',
    'notes = [engine.hide_words(n) for n in', 'prefix + engine.hide_words(text).strip()'])
def test_the_review_page_and_chat_star_what_they_show(shown):
    assert shown in SRC
