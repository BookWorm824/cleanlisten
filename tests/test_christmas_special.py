"""From CleanView 1.18.120 (Call the Midwife's Christmas special, 2026-11-17), carried over by her
rule that words go to CleanListen and CleanRead too: the nativity counts as Christmas, "the baby
Jesus" and "his name will be Jesus" aren't oaths, and "titty birds" is "dicky birds" misheard."""
import pytest

import cleanlisten as E
import cleanlisten_claude as cc


def words(text):
    return [E.norm(w) for w in text.split()]


def found(text, cats):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, list(cats))]


@pytest.mark.parametrize("text", [
    "The children put on a nativity play.", "We opened the Advent calendar.", "Light the Advent candle.",
    "Advent is nearly here.", "Away in a manger, no crib for a bed.", "They travelled to Bethlehem.",
    "The three wise men followed the star.", "Gold, frankincense and myrrh.", "We sang Silent Night.",
    "Hark the herald angels sing.", "O come all ye faithful.", "We three kings of Orient are.",
    "The first Noel the angels did say.", "Deck the halls with boughs of holly.",
    "She made mince pies.", "Three kings came to the stable.",
])
def test_the_nativity_is_christmas(text):
    assert E.topic_hit("holiday", words(text)), text


@pytest.mark.parametrize("text", [
    "The advent of the railway changed everything.", "With the advent of spring.",
    "Don't be a dog in the manger.", "He worked at Bethlehem Steel.", "The shepherds watched the sheep.",
    "An angel of a child.",
])
def test_not_the_nativity(text):
    assert not E.topic_hit("holiday", words(text)), text


@pytest.mark.parametrize("text", [
    "They laid the baby Jesus in the straw.", "His name will be Jesus.", "They named him Jesus.",
    "And you shall call his name Jesus.",
])
def test_reverent_jesus_kept(text):
    assert not found(text, ["deity"]), text


def test_sweet_baby_jesus_is_still_an_oath():
    assert found("Sweet baby Jesus, look at that!", ["deity"])


def test_dicky_birds_misheard():
    assert not found("Two little titty birds sitting on a wall.", ["sexual"])
    assert found("Nice titty.", ["sexual"])


def test_the_readers_are_told():
    for text in (E.AI_TYPES["holiday"], cc.KIND_RULES["holiday"]):
        assert "nativity" in text and "Advent" in text
