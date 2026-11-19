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
