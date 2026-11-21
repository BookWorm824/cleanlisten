"""CleanView 1.18.157 (the owner, in the CleanStream chat: "jerk me off should go in the sex catogory for
all"): "jerk/jack <someone> off" is a sexual word; "jerked him off his feet", "jerked her off the ledge"
stay, and "jerk" alone is still a rude word."""
import pytest

import cleanlisten as E


def found(text, cats=("sexual", "rude")):
    ws = [E.norm(t) for t in text.split() if E.norm(t)]
    return [(" ".join(ws[a:b]), c) for a, b, c in E.find_language(ws, list(cats))]


@pytest.mark.parametrize("text, phrase", [
    ("Jerk me off.", "jerk me off"), ("He was jerking himself off.", "jerking himself off"),
    ("She jerked him off in the car.", "jerked him off"), ("Jack me off.", "jack me off"),
    ("They jerk each other off.", "jerk each other off"), ("He jacks you off.", "jacks you off"),
])
def test_it_is_a_sexual_word(text, phrase):
    assert (phrase, "sexual") in found(text)


@pytest.mark.parametrize("text", [
    "The wave jerked him off his feet.", "She jerked her off the ledge.", "It jerked him off the horse.",
    "The blast jerked them off the roof.", "The car jerked off the road.",
])
def test_everyday_uses_stay(text):
    assert found(text) == []


def test_jerk_alone_is_still_rude():
    assert found("What a jerk!") == [("jerk", "rude")]
    assert found("What a jerk!", ["sexual"]) == []
