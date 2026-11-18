"""CleanView 1.18.134 (When Calls the Heart), carried over: a dam heard as the swear, and "Dear Lord,
please ..." said to God."""
import pytest

import cleanlisten as E

ALL = ["strong", "moderate", "mild", "deity", "minced", "sexual", "rude"]


def found(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ALL)]


@pytest.mark.parametrize("text", [
    "doing everything in my power to hold the damn back", "the damn burst after the rain",
    "a beaver damn on the creek", "Dear Lord, please help us.", "Dear God, thank you for this day.",
    "Dear Lord, forgive me.",
])
def test_left_alone(text):
    assert not found(text), text


@pytest.mark.parametrize("text", ["Close the damn back door!", "that damn dog", "Dear God, when I came here",
                                  "Oh dear God!"])
def test_still_caught(text):
    assert found(text), text
