"""CleanView 1.18.133 (Christy's pilot, Criminal Minds S1E3/S1E5; the owner: "Yes, fix them"), carried over
to CleanListen and CleanRead: the raccoon, "sex" meaning boys or girls, "Thank God and seek ...", "hooked up
with ATF", and impotent."""
import pytest

import cleanlisten as E
import cleanread as R

ALL = ["strong", "moderate", "mild", "deity", "minced", "sexual", "rude"]


def words(text):
    return [w for w in (E.norm(t) for t in text.split()) if w]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ALL)]


@pytest.mark.parametrize("text", ["The pet coon washes everything before it eats.",
                                  "They be the best pets, a coon in a cage.",
                                  "each grade together regardless of sex", "children of either sex",
                                  "sorted by age and sex", "Thank God and seek faith.",
                                  "Thank the Lord and praise Him.", "Morgan hooked up with ATF.",
                                  "We hooked up with the local police.", "impotent rage",
                                  "the drug was impotent against the infection"])
def test_left_alone(text):
    assert not found(text), text


@pytest.mark.parametrize("text", ["You dirty coon!", "she hooked up with him last night", "He's impotent.",
                                  "a sex offender's sex life"])
def test_still_caught(text):
    assert found(text), text


def test_sleeping_around_and_old_books():
    assert not R.SLEEPING(words("Morgan hooked up with ATF"))
    assert R.SLEEPING(words("she hooked up with him"))
    assert R._ref_hit(words("He's impotent."))
    assert not R._ref_hit(words("the impotent man was healed"), old_style=True)
