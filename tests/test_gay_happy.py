""""Gay" meaning happy in older books is left alone before these words (CleanView 1.18.94; the owner,
2026-11-14, of I Love Lucy: "this is an old show so gay means happy")."""
import pytest

import cleanlisten as E
from conftest import words

LEFT = ["Your life should be just one gay round of nightclubs.", "We had a gay old time at the fair",
        "everyone was in gay spirits", "the gay music of the band", "a gay tune on the fiddle",
        "the gay colours of the market", "a gay evening of dancing", "the gay festivities went on"]
COUNTED = ["They are a gay couple.", "They went to a gay bar.", "He is gay."]


@pytest.mark.parametrize("line", LEFT)
def test_happy_is_left(line):
    assert E.find_language(words(line), ["orientation"]) == []


@pytest.mark.parametrize("line", COUNTED)
def test_the_other_meaning_still_counts(line):
    assert E.find_language(words(line), ["orientation"])
