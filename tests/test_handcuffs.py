"""Handcuffs as innuendo (CleanView 1.18.163; the owner: "add handcuffs to the list when used as
inuendo"): furry cuffs, "cuff me to the bed", "handcuffs for the bedroom", "kinky" near them. Not police
cuffing someone, a patient cuffed to a bed, or a shirt's silk cuffs."""
import pytest

import cleanlisten as E
import cleanread as R


def w(text):
    return [E.norm(t) for t in text.split() if E.norm(t)]


@pytest.mark.parametrize("line", [
    "She bought furry handcuffs.", "A pair of fuzzy cuffs.", "Pink handcuffs, really?",
    "Cuff me to the bedpost.", "He handcuffed you to the bed?", "Handcuffs for the bedroom, huh?",
    "We tried something kinky with the handcuffs.", "Handcuffs? How naughty.",
])
def test_innuendo(line):
    assert R._ref_hit(w(line)), line
    assert E.find_language(w(line), ["sexual"]), line


@pytest.mark.parametrize("line", [
    "Cuff him.", "Seventy-five cops in cuffs.", "The patient was cuffed to the bed.",
    "He cuffed her to the bed rail.", "Her silk cuffs were frayed.", "Velvet cuffs on his coat.",
    "Put the handcuffs on him. That kid is naughty.",
])
def test_left_alone(line):
    assert not E.find_language(w(line), ["sexual"], breaks={w(line).index("that")} if "That" in line else ()), line


def test_kinky_near_cuffs_mutes_the_cuffs_word():
    ws = w("We tried something kinky with the handcuffs.")
    spans = [(" ".join(ws[a:b]), c) for a, b, c in E.find_language(ws, ["sexual"])]
    assert ("handcuffs", "sexual") in spans
