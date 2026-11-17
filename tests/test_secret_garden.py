"""Lessons from The Secret Garden (the night run's report, 2026-11-17, checked in the book): "shut up"
meaning closed, "spick an' span", a lamb at its bottle (butt its head, suck it, ecstasy), a bird
flirting its tail, things slapped down, what would have happened, an animal's mother killed, and a
bottomless lake. The real thing is still found in each case."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words


CATS = list(E.ALL_CATS) + ["rude"]


def found(text, cats):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, cats)]


@pytest.mark.parametrize("text", [
    "There's near a hundred rooms in it, nearly all shut up and with their doors locked.",
    "the garden which was shut up", "since it was shut up ten year'", "that poor lad lyin' shut up",
    "most of them's shut up and locked",
])
def test_shut_up_meaning_closed(text):
    assert "shut up" not in found(text, CATS), text


@pytest.mark.parametrize("text", ["Shut up, said Peter.", "You shut up!", "Oh, shut up and listen."])
def test_shut_up_said_to_someone_still_found(text):
    assert "shut up" in found(text, CATS), text


def test_lamb_and_spick_and_span():
    assert found("all clipped an' spick an' span", CATS) == []
    assert found("nuzzle into its folds and butt its tight-curled head", CATS) == []
    assert found("the lamb began to suck it with ravenous ecstasy", CATS) == []
    assert not R.DRUGS(words("he pushed the rubber tip of the bottle into the nuzzling mouth and the lamb "
                             "began to suck it with ravenous ecstasy"))
    assert not R.DRUGS(words("leaving ecstasy and nudging elbows and little jumps of joy behind"))


def test_the_real_ones_still_found():
    assert found("Suck it, loser!", CATS)
    assert R.DRUGS(words("They took ecstasy pills at the rave."))
    assert found("Get your fat butt over here.", CATS)


def test_a_bird_flirting_its_tail():
    assert not E.flirt_hit(words("and flirted his tail and twittered"))
    assert not E.flirt_hit(words("until the robin gave another flirt to his wings and flew away"))
    assert E.flirt_hit(words("She flirted with the waiter all night."))


@pytest.mark.parametrize("text", [
    "She slapped it open with her hand and ran across the room.",
    "she slapped it down on the kitchen dresser",
    "If you had been his own boy and he had been a slapping sort of man, he would have slapped you.",
    "Its mother had been killed nearby and the rest of the litter was dead.",
])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


@pytest.mark.parametrize("text", ["She slapped him across the face.", "He slapped her hard.",
                                  "The man killed his neighbour."])
def test_violence_still_found(text):
    assert R.VIOLENCE(words(text)), text


def test_a_bottomless_lake():
    assert not R.NUDITY(words("like the waters of some lovely bottomless lake"))
    assert R.NUDITY(words("She was a bottomless dancer."))
