"""From CleanView 1.18.125 (Criminal Minds S1E1), carried over by her words rule: rape, raped, rapist and
raping are case talk (not only "was raped"), never therapist, grape, rapeseed or rapier; "without
penetration" is an explicit finding."""
import pytest

import cleanlisten as E
import cleanread as R


def words(text):
    return [E.norm(w) for w in text.split()]


@pytest.mark.parametrize("text", ["The rapist was caught.", "He raped two women.", "A rape in the park.",
                                  "Reports of rapes went up.", "He was raping them for years."])
def test_rape_talk_is_case_talk(text):
    assert R.MEDICAL(words(text)), text


@pytest.mark.parametrize("text", ["She saw a therapist.", "A bunch of grapes.", "Fields of rapeseed.",
                                  "He drew his rapier."])
def test_not_rape_talk(text):
    assert not R.MEDICAL(words(text)), text


def test_without_penetration_is_explicit():
    ws = words("assaulted but without penetration")
    assert E.explicit_finding_words(ws) == {2, 3}


def test_without_penetration_isnt_muted_as_a_word_on_its_own():
    # as CleanView: only an explicit finding (the line goes), not a sexual word muted by itself
    ws = words("assaulted but without penetration")
    assert not [s for s in E.find_language(ws, ["sexual"]) if ws[s[0]] == "without"]
