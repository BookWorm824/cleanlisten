"""Castle S2E19-24 (CleanView 1.18.162; the owner: "Yes, both", words going to every app): "banging my
daughter" and "I would've done her" (at the end of a sentence) are sexual references; two-timing, a tryst
and sleeping with everyone are sleeping around (a tryst only in a modern book: in the classics it's an
innocent meeting)."""
import pytest

import cleanlisten as E
import cleanread as R


def w(text):
    return [E.norm(t) for t in text.split() if E.norm(t)]


@pytest.mark.parametrize("line", [
    "He was banging my daughter right under my nose?", "Is he banging his secretary?",
    "I would've done her.", "I would maybe do her.", "Yeah, but I'd do her.", "I'd totally do him.",
])
def test_sexual_references(line):
    assert R._ref_hit(w(line)), line


@pytest.mark.parametrize("line", [
    "Susan banged her pots about wrathfully.", "I wanted to bang their pert black noses together.",
    "I'd do her hair for the wedding.", "I'd do her a favor.", "It would have done him good.",
    "They'd done her in.", "Bang! went the door.",
])
def test_left_alone(line):
    assert not R._ref_hit(w(line)), line


@pytest.mark.parametrize("line", [
    "He's a two-timing jerk.", "She two-timed him all summer.", "They had a tryst at the motel.",
    "He sleeps with everybody.", "She was sleeping with every guy in the office.",
])
def test_sleeping_around(line):
    assert R.SLEEPING(w(line)), line


@pytest.mark.parametrize("line", [
    "Captain Jim kept a passing tryst with visitants.", "the glade before the trysting tree",
    "Jem and Faith trysted there considerably.",
])
def test_a_tryst_in_an_older_book_is_a_meeting(line):
    assert not R.old_sleeping_hit(w(line), True), line


def test_two_times_three():
    assert not R.SLEEPING(w("Two times three is six."))
