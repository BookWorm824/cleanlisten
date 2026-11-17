"""Lessons from The Swiss Family Robinson (the night run's report, 2026-11-17, checked in the book). The
real thing is still found in each case."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import OLD, _book

CATS = list(E.ALL_CATS) + ["rude"]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, CATS)]


def kinds(an):
    return [c["kind"] for c in an["cuts"]]


@pytest.mark.parametrize("text", [
    "I have found on board the ship, a cow and an ass, two goats, six sheep",
    "Camels and asses are very fond of thistles",
    "lighting up a faggot of dried bamboo, and quickly roasting",
    "gulls, man of war birds, boobies, albatrosses, and a crowd of others",
    "each of the boys seized one of the sugarcanes and began to suck it",
    "when I have sucked this part dry",
    "and then a second jerk, accompanied by a rapid motion of the boat",
    "We all cast our eyes upon the pot with a sort of silent and stupid perplexity",
])
def test_not_bad_words(text):
    assert found(text) == [], text


def test_bad_words_still_found():
    assert found("You ass, Toad!")
    assert found("Don't be such an ass.")
    assert found("That's stupid.")
    assert found("Life sucks.")
    assert found("He called him a faggot.")


def test_a_book_with_a_donkey(tmp_path):
    book = _book(tmp_path, OLD + ["We brought the cow and the ass ashore.", "The ass carried the load.",
                                  "The ass began to kick at the goats.", "Let us not treat even our ass with disdain.",
                                  "Jack, you ass, said Fritz."], "donkey")
    an = R.analyze(book, dict(swearing=True, mild=True, rude=True))
    assert [m["word_raw"] for m in an["mutes"]] == ["ass"]
    assert book.paras[an["mutes"][0]["para"]].text.startswith("Jack")


@pytest.mark.parametrize("text", ["the trees were so high as to be out of gunshot reach",
                                  "I hastened to loosen the cord and prevent its being strangled.",
                                  "to stupefy without killing the little warlike creatures",
                                  "with a piece of the slaughtered buffalo's skin"])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


def test_other_cuts():
    assert not R.DISTURBING(words("We accordingly hastened to the execution of our design."))
    assert R.DISTURBING(words("The execution of the prisoner took place at dawn."))
    assert not R.IMMODEST(words("I added a thong of leather."))
    assert R.IMMODEST(words("She wore a thong on the beach."))
    assert not R.MEDICAL(words("I made deep incisions in the trunks of the palms."))
    assert not R.SMOKING(words("burning a few handfuls of tobacco to stupefy the bees"))
    assert not R.DRINKING(words("an ointment of butter and wine for the wound"))
    assert not R.UNMARRIED(words("a swarm of birds living together in one nest"))


def test_hunting_for_food(tmp_path):
    book = _book(tmp_path, OLD + ["Ernest went out with his gun after the birds.",
                                  "My wife set about stripping off the feathers of the birds Ernest had killed.",
                                  "Then we all sat down to supper together.",
                                  "Cain killed his brother in the field."], "hunting")
    an = R.analyze(book, dict(violence=True))
    assert [c["raw"] for c in an["cuts"] if c["kind"] == "violence"] == ["Cain killed his brother in the field."]
