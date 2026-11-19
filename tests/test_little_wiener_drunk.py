"""CleanView 1.18.137/138's last three word rules, carried over (the owner's standing rule: word, phrase,
guard and filter changes go to CleanView, CleanListen and CleanRead): "little wiener" and "rubbing his
ball(s)" as sexual references, and "drunk" muted as just the word under crude humor."""
import pytest

import cleanlisten as E
import cleanread as R


def found(text, cats):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, cats)]


@pytest.mark.parametrize("text, words", [
    ("He has a little wiener.", "little wiener"), ("Nice little weenie, pal.", "little weenie"),
    ("She was rubbing his balls.", "rubbing his balls"), ("He kept rubbing his ball.", "rubbing his ball"),
])
def test_sexual_references(text, words):
    assert words in found(text, ["sexual"]), text


@pytest.mark.parametrize("text", [
    "My little wiener dog ran off.", "We ate a little weenie on a bun.",
    "The pitcher was rubbing his ball on the mound.", "The fortune teller kept rubbing her crystal ball.",
])
def test_dogs_food_and_games_left(text):
    assert not found(text, ["sexual"]), text


@pytest.mark.parametrize("text, words", [
    ("He was drunk.", "drunk"), ("She's drunk", "drunk"), ("a drunken sailor", "drunken"),
    ("the town drunkard", "drunkard"), ("He came home drunk again.", "drunk"),
    ("She walked drunkenly home.", "drunkenly"),
])
def test_drunk_just_the_word(text, words):
    assert found(text, ["crude"]) == [words], text


@pytest.mark.parametrize("text", [
    "He had drunk his tea.", "She's drunk the water.", "They had drunk from the well.",
    "We have drunk deeply of the cup.", "And the toast was drunk in ginger wine and water.",
    # older books (the classics)
    "the first regular toast, which was always drunk at such times",
    "the nectar drunk by the gods", "till thou'st drunk to the Prince of Wales",
    "I was so drunk with the joy of it I lost all me sense",
])
def test_what_was_drunk_left(text):
    assert not found(text, ["crude"]), text


@pytest.mark.parametrize("text", [
    "He was drunk by noon.", "They were drunk by the time we got there.", "He was always drunk.",
    "They got drunk with their friends.",
    # CleanView 1.18.140: a person in the sentence means someone is drunk
    "The beer was cold and he was drunk.", "The guy who drank the whiskey was drunk.",
    "The wine was gone, but she was drunk.",
])
def test_still_being_drunk(text):
    assert found(text, ["crude"]) == ["drunk"], text


def test_drunk_ending_a_sentence_in_a_book():
    ws = [w for w in (E.norm(t) for t in "She's drunk. The cup was empty.".split()) if w]
    assert E.find_language(ws, ["crude"], breaks={2}) == [(1, 2, "crude")]


def test_crude_humor_ticked_brings_the_drunk_words():
    assert "crude" in R.chat_filters({"crude": True})["cats"]
    assert "crude" not in R.chat_filters({"crude": False})["cats"]


def test_drink_in_the_last_sentence_does_not_count():
    ws = [w for w in (E.norm(t) for t in "We had tea. He was drunk.".split()) if w]
    assert E.find_language(ws, ["crude"], breaks={3}) == [(5, 6, "crude")]


# CleanView 1.18.142 (DRUNK_WHOSE): only nothing, or whose it was ("of"/"to"), between the drink and "was"
@pytest.mark.parametrize("text", [
    "The owner of the wine shop was drunk.", "The driver of the beer truck was drunk.",
    "A glass of wine and Tom was drunk.", "Two drinks and Tom was drunk.",
])
def test_a_person_after_the_drink_is_drunk(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    assert E.find_language(ws, ["crude"]), text


@pytest.mark.parametrize("text", [
    "And the toast was drunk in ginger wine.", "The health of his majesty was drunk.",
    "The toast to the bride was drunk standing.", "The beer and the wine were drunk.",
    "Her coffee was drunk cold.",
])
def test_what_was_drunk_still_left(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    assert not E.find_language(ws, ["crude"]), text


# the free classics re-check (2026-11-19): what was drunk, in older books
@pytest.mark.parametrize("text", [
    "the loving-cup has always been drunk at English banquets",
    "currant wine was not meant to be drunk three tumblerfuls at a time",
    "a most surprising number of the bottles had been drunk out",
])
def test_classics_what_was_drunk(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    assert not E.find_language(ws, ["crude"]), text


@pytest.mark.parametrize("text", [
    "Set Diana drunk!", "They got drunk whenever they could.", "the men were lying drunk below",
    "The wine was gone, but she was drunk.", "The beer was cold and he was drunk.",
])
def test_classics_still_drunk(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    assert E.find_language(ws, ["crude"]), text
