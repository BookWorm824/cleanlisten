"""New words under Drugs (the owner, 2026-11-18: "out these under drugs", "perkaset", "roofie", "roofies")."""
import pytest

import cleanlisten as E
import cleanread as R


def words(text):
    return [w for w in (E.norm(t) for t in text.split()) if w]


@pytest.mark.parametrize("text", ["He was hooked on Percocet.", "She was popping perkasets.", "Somebody slipped her a roofie.",
                                  "They found roofies in his car.", "I think she was roofied.", "traces of Rohypnol"])
def test_drug_words(text):
    assert R.DRUGS(words(text)), text


def test_not_drugs():
    assert not R.DRUGS(words("The roof leaked all winter."))
    # Percocet only when it's misused (the owner: "only misusing")
    assert not R.DRUGS(words("The doctor prescribed Percocet for her back."))
    assert not R.DRUGS(words("She took two Percocets after the surgery."))
    assert R.DRUGS(words("He bought Percocet off a guy at the gas station."))


def test_booger_sugar():
    # the owner, 2026-11-18: "also add \"booger sugar\""
    assert R.DRUGS(words("He did a little booger sugar before the show."))


# CleanView 1.18.137: the drug slang she chose ("group 1 only"), with its guards
@pytest.mark.parametrize("text", ["He was a total pothead.", "They passed the spliff around.", "smoking kush",
                                  "She had track marks up her arm.", "he was strung out on pills",
                                  "jonesing for a fix", "a few Xanax bars", "he was selling OxyContin on the street",
                                  "a line of nose candy", "magic mushrooms", "He was tripping balls.",
                                  "Somebody gave her ruffies.", "a crackhead on the corner"])
def test_drug_slang(text):
    assert R.DRUGS(words(text)), text


@pytest.mark.parametrize("text", ["The wagon left track marks in the mud.", "the Hindu Kush mountains",
                                  "the riders were strung out along the road", "I've been jonesing for you",
                                  "Doc prescribed OxyContin after surgery"])
def test_drug_slang_other_meanings(text):
    assert not R.DRUGS(words(text)), text
