"""Person of Interest S1E4 words (CleanView 1.18.105): someone's "conquests"."""
import pytest

import cleanlisten as E

ALL = list(E.ALL_CATS) if hasattr(E, "ALL_CATS") else ["strong", "moderate", "mild", "minced",
                                                        "deity", "sexual"]


def hits(text, cats=ALL):
    ws = [E.norm(w) for w in text.split() if E.norm(w)]
    return [(" ".join(ws[i:j]), c) for i, j, c in E.find_language(ws, cats)]


@pytest.mark.parametrize("text, said", [
    ("Benton's conquests?", "conquests"),
    ("So I could be another one of your conquests?", "conquests"),
    ("He bragged about his conquests.", "conquests"),
    ("She was his latest conquest... no, her conquest.", "conquest"),
])
def test_conquests_found(text, said):
    assert (said, "sexual") in hits(text)


@pytest.mark.parametrize("text", ["the Norman Conquest", "the conquest of Mexico", "Conquest is a game.",
                                  "That's conquest enough for one day.", "It's conquest or nothing."])
def test_other_conquests_left(text):
    assert hits(text) == []


def test_conquests_need_the_sexual_words():
    assert hits("Benton's conquests?", ["strong", "mild"]) == []
