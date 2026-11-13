"""Sexual-reference phrases from Castle S2E3 (CleanView 1.18.69; the owner, 2026-11-12, every app):
skinny dip, chastity belt, naked photos / pictures / selfies. Not "skinny dippers" (police talk),
"the naked eye" or "the naked truth".
Castle S2E1 (CleanView 1.18.84; the owner, 2026-11-13: "if pole ever comes after stripper it should be
muted, keep pole other instances")."""
import pytest

import cleanlisten as E

CATCH = ["Oh, a fountain! Let's skinny dip!", "We went skinny-dipping at the lake.", "They skinny dipped.",
         "she might as well be wearing a chastity belt.", "Mmm. Naked photos.",
         "Look at naked pictures? If you insist.", "He sent her naked selfies.",
         "She slid down the stripper pole.", "They put in two stripper poles.",
         "It was the stripper's pole."]
LEAVE = ["A couple of skinny dippers found her this morning.", "Can you see it with the naked eye?",
         "That's the naked truth.", "a skinny guy dipped his fries", "She was naked under the sheet.",
         "Santa lives at the North Pole.", "He brought a fishing pole.", "Up the flag pole it went.",
         "She won the pole vault.", "Pack the tent poles.", "The pole was ten feet tall."]


def words(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


@pytest.mark.parametrize("line", CATCH)
def test_caught(line):
    assert E.find_language(words(line), ["sexual"])


@pytest.mark.parametrize("line", LEAVE)
def test_left_alone(line):
    assert not E.find_language(words(line), ["sexual"])


def test_just_the_words_are_muted():
    w = words("Look at naked pictures? If you insist.")
    (i, j, cat), = E.find_language(w, ["sexual"])
    assert w[i:j] == ["naked", "pictures"] and cat == "sexual"
    w = words("She slid down the stripper pole at the North Pole.")
    (i, j, cat), = E.find_language(w, ["sexual"])
    assert w[i:j] == ["stripper", "pole"] and cat == "sexual"
