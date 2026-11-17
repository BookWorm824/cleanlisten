"""From CleanView 1.18.126 (asked for in the CleanStream chat): masturbate in every form, and its common
misspelling "masterbate", is muted as a word; not "master bathroom" or "mastery"."""
import pytest

import cleanlisten as E


def found(text):
    ws = [E.norm(w) for w in text.split()]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, list(E.PHRASES))]


@pytest.mark.parametrize("text", ["He would masturbate.", "masterbating again", "the masturbator",
                                  "masturbatory jokes", "a masterbation joke", "He masturbated."])
def test_muted(text):
    assert found(text), text


@pytest.mark.parametrize("text", ["the master bathroom", "Mastery of the subject", "a master baker"])
def test_left(text):
    assert not found(text), text
