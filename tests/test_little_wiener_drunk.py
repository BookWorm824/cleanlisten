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
