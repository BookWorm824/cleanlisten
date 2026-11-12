"""Sexual-reference phrases from Castle S2E3 (CleanView 1.18.69; the owner, 2026-11-12, every app):
skinny dip, chastity belt, naked photos / pictures / selfies. Not "skinny dippers" (police talk),
"the naked eye" or "the naked truth"."""
import pytest

import cleanlisten as E

CATCH = ["Oh, a fountain! Let's skinny dip!", "We went skinny-dipping at the lake.", "They skinny dipped.",
         "she might as well be wearing a chastity belt.", "Mmm. Naked photos.",
         "Look at naked pictures? If you insist.", "He sent her naked selfies."]
LEAVE = ["A couple of skinny dippers found her this morning.", "Can you see it with the naked eye?",
         "That's the naked truth.", "a skinny guy dipped his fries", "She was naked under the sheet."]


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
