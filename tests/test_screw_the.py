"""CleanView 1.18.139 (Criminal Minds S1E9; the owner: "Yes, fix both"), carried over: "screw the <word>"
is muted with the mild words, like "screw you", but not a thing being fixed ("screw the lid on")."""
import pytest

import cleanlisten as E


def found(text, breaks=()):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ["mild"], breaks=breaks)]


@pytest.mark.parametrize("text, words", [
    ("Screw the government.", "screw the government"), ("Screw the show and the Greenwoods.", "screw the show"),
    ("Screw the Columbians!", "screw the columbians"), ("Screw the rules", "screw the rules"),
])
def test_muted(text, words):
    assert found(text) == [words], text


@pytest.mark.parametrize("text", [
    "Screw the lid on tight.", "screw the bulb back in", "He had to screw the panel down.",
    "screw the courage to the sticking place", "Tighten the screw the other way.",
    "Screw the two pieces together.",
])
def test_fixing_things_left(text):
    assert not found(text), text


def test_not_across_sentences():
    # "...a loose screw. The lid..." in a book: "screw" ends one sentence
    assert not found("He found a screw. The lid was off.", breaks={4})
