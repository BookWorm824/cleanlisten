"""Lessons from Little Women (the night run's report, 2026-11-17, checked in the book). The real thing
is still found in each case."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import MODERN, OLD, _book

CATS = list(E.ALL_CATS) + ["rude"]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, CATS)]


@pytest.mark.parametrize("text", ["She sat with her darning-needle.", "darning hose by the fire",
                                  "I like his neat darns.", "He darned his own socks.",
                                  "she eats one before her face, and don't offer even a suck",
                                  "quieted all pricks of conscience"])
def test_not_bad_words(text):
    assert found(text) == [], text


def test_bad_words_still_found():
    assert "darn" in found("Darn it all!") or found("Darn it all!")
    assert found("That darned dog again.")
    assert found("Life sucks.")


def test_old_book_words(tmp_path):
    book = _book(tmp_path, OLD + [
        "for the cot-bed, on which the dress-circle was built, suddenly shut up.",
        "He keeps his grandson shut up, when he isn't riding.",
        "I've been sick with this cold so long, and shut up, I'm dying for some fun.",
        "the once smiling lips quite dumb", "Plumfield overrun with Toms, Dicks, and Harrys!",
        "Shut up, said Jo.", "Sit down and shut up."], "old_women")
    assert book.old_style
    an = R.analyze(book, dict(rude=True, swearing=True))
    assert [m["word_raw"] for m in an["mutes"]] == ["Shut up", "shut up"]


@pytest.mark.parametrize("text", ["feeling as if she had murdered some innocent thing",
                                  "she felt as if she had stabbed her dearest friend",
                                  "I won't beat you if you have got a pair of killing boots",
                                  "I always wanted to do the killing part.",
                                  "who was in a fair way to be killed by kindness"])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


def test_other_cuts():
    assert not R.DISTURBING(words("and looked ready to carry his threat into execution"))
    assert not R.DRINKING(words("for he has Scotch blood in him"))
    assert not R.SMOKING(words("that he has given up smoking"))
    assert R.SMOKING(words("smoking like bad chimneys"))
    assert not E.bully_hit(words("but don't kill yourself driving at a desperate pace"))
    assert E.bully_hit(words("Go kill yourself."))
    assert not E.bully_hit(words("Some make fun of it, some overpraise."))
    assert not E.crude_hit(words("that was thorn number two"))
    assert E.crude_hit(words("I need to go number two."))
    assert not E.crude_hit(words("The musicians fiddled, tooted, and banged"))
