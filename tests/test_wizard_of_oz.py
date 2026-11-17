"""Lessons from The Wonderful Wizard of Oz (the night run's report, 2026-11-17, checked in the book):
"killed" when nobody is killed, by a smell, or of an animal. The real thing is still found."""
import pytest

import cleanread as R
from conftest import words


@pytest.mark.parametrize("text", [
    "You are very kind, but there must be some mistake. I have not killed anything.",
    "she had never killed anything in all her life",
    "I never killed anything, willingly, she sobbed.",
    "The smell of the flowers is killing us all.",
    "yet such little things as flowers came near to killing me",
    "This funny tin man killed the Wildcat and saved my life.",
    "Once, indeed, the Tin Woodman stepped upon a beetle that was crawling along the road, and killed the poor little thing.",
])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


@pytest.mark.parametrize("text", [
    "The house fell on the witch and killed her.", "He killed the guard and ran.",
    "He fought the wolf with his axe and killed it.", "They never stopped; they killed him anyway.",
])
def test_still_violence(text):
    assert R.VIOLENCE(words(text)), text


def test_aroused_meaning_woke():
    import cleanlisten as E
    assert E.find_language(words("So the Lion aroused himself and bounded forward"), ["sexual"]) == []
    assert E.find_language(words("The noise aroused his curiosity."), ["sexual"]) == []
    assert E.find_language(words("She was aroused by his touch."), ["sexual"])
