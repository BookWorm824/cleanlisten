"""Person of Interest S1E2 words (CleanView 1.18.102): a listed word with 'd/'ll/'re/'ve joined
on, and stepping out on / cheating on a person."""
import pytest

import cleanlisten as E

ALL = list(E.ALL_CATS) if hasattr(E, "ALL_CATS") else ["strong", "moderate", "mild", "minced",
                                                        "deity", "sexual"]


def found(text, cats=ALL):
    ws = [E.norm(w) for w in text.split() if E.norm(w)]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, cats, lead_in_too=True)]


@pytest.mark.parametrize("text, want", [
    ("How the hell'd you get in here?", "how the hell'd"),
    ("Who the hell're you?", "who the hell're"),
    ("The hell'll it matter", "hell'll"),
    ("That damn'd dog", "damn'd"),
])
def test_contracted_swear_found(text, want):
    assert want in found(text)


@pytest.mark.parametrize("text", ["He'd go there", "We'll see", "Shell'd be fine", "They're here",
                                  "I've got it", "I'd like that", "You'd better"])
def test_contracted_plain_left(text):
    assert found(text) == []


@pytest.mark.parametrize("text, want", [
    ("He stepped out on her.", "stepped out on her"),
    ("She's been stepping out on her husband.", "stepping out on her husband"),
    ("He cheated on his wife.", "cheated on his wife"),
    ("My man don't step out on me.", "step out on me"),
    ("If you're gonna step out on your wife, you need to think it through",
     "step out on your wife"),
    ("He was cheating on his fiancée", "cheating on his fiance"),
])
def test_stepping_out_found(text, want):
    assert found(text, ["sexual"]) == [want]


@pytest.mark.parametrize("text", ["Step out on the balcony.", "She stepped out on her porch.",
                                  "He cheated on his taxes.", "Did you cheat on the test?",
                                  "He stepped out on the ice"])
def test_stepping_out_left(text):
    assert found(text, ["sexual"]) == []


def test_stepping_out_off_without_sexual_words():
    assert found("He cheated on his wife.", ["strong", "moderate", "mild"]) == []
