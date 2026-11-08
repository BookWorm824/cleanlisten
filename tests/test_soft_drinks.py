"""A drink of water or milk isn't drinking (The Boxcar Children, 2026-11-07, via CleanView: four
sentences about water and milk were flagged as drinking)."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words


@pytest.mark.parametrize("text", [
    "\u201cI want a drink of water, Henry!\u201d said Benny.",
    "When Henry comes, we can eat some blueberries and then take a drink of milk.",
    ", then take a drink of milk",
    "She took a drink of cold water from the cup.",
    "He took a long drink from the brook.",
    "Benny had a drink from the cool spring.",
    "Let's have a drink of hot chocolate.",
])
def test_water_and_milk_arent_drinking(text):
    w = words(text)
    assert R.DRINKING(w) == [] and R.SUBSTANCES(w) == []
    assert not E.sentence_hit("drinking", w)


@pytest.mark.parametrize("text", [
    "He poured himself a drink and sat down.",
    "She ordered another drink at the bar.",
    "He had a drink of whiskey before dinner.",
    "a drink from the bar", "a drink of", "Let me buy you a drink",
    "He took a drink of the strong stuff.",
])
def test_other_drinks_still_count(text):
    w = words(text)
    assert R.DRINKING(w) and R.SUBSTANCES(w)
    assert E.sentence_hit("drinking", w)


def test_whiskey_in_a_water_sentence_still_counts():
    w = words("He had a drink of water and then a glass of whiskey.")
    assert R.DRINKING(w)
