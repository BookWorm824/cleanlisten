"""CleanView 1.18.141 (Criminal Minds S1E11), carried over: "I wish to God..." and "I hope to God..."
are God's name like "swear to God"; "pray to God" stays a prayer."""
import pytest

import cleanlisten as E


def found(text):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ["deity"])]


@pytest.mark.parametrize("text, words", [
    ("I WISH TO GOD HE'D NEVER SPOKEN TO YOU!", "wish to god"), ("I hope to God he's okay.", "hope to god"),
    ("She wished to God she'd stayed home.", "wished to god"), ("He hoped to God it would hold.", "hoped to god"),
])
def test_muted(text, words):
    assert words in found(text), text


def test_a_prayer_stays():
    assert not found("We pray to God every night.")
