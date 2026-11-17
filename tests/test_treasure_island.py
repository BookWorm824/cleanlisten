"""Lessons from Treasure Island (the night run's report, 2026-11-17, checked in the book). The real
thing is still found in each case."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words

CATS = list(E.ALL_CATS) + ["rude"]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, CATS)]


def test_smoke_that_isnt_smoking():
    assert not R.SMOKING(words("they fired again with smoking muskets"))
    assert not R.SMOKING(words("which were almost smoked out of his head"))
    assert R.SMOKING(words("He smoked his pipe by the fire."))


@pytest.mark.parametrize("text", ["Doctor Livesey fairly slapped his thigh.", "slapping tables with his hand",
                                  "and slapped him on the back", "There's where I killed my first goat.",
                                  "Care killed a cat."])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


def test_slaps_still_violence():
    assert R.VIOLENCE(words("He slapped her across the face."))


def test_not_disturbing():
    assert not R.DISTURBING(words("I now began to be tortured with thirst."))
    assert not R.DISTURBING(words("I'll be hanged if I'll be hazed by you, John Silver."))
    assert R.DISTURBING(words("He was hanged in chains."))


def test_rum_puncheon_is_a_barrel():
    assert not R.DRINKING(words("stove in your old blockhouse like a rum puncheon"))
    assert R.DRINKING(words("Yo-ho-ho and a bottle of rum!"))


def test_old_words():
    assert found("something of a butt with the country boys") == []
    assert found("you ain't dumb, I reckon") == []
    assert found("This second trip fairly aroused the watchers along shore.") == []
    assert "dumb" in found("You dumb idiot!")
