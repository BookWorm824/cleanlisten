"""Castle S2E10's sleeping-around lines (CleanView 1.18.161; the owner: "Yes, both", words going to every
app): someone's affair, one that lasted a while, refusing to sleep with someone, cheating on a sister or
a friend. Not in an older book, where they mean someone's business or two boys sharing a bed; not
"cheated on his taxes"."""
import pytest

import cleanlisten as E
import cleanread as R


def w(text):
    return [E.norm(t) for t in text.split() if E.norm(t)]


CASTLE = ["I guess Helen did know about her husband's affair.",
          "If she thinks that her six-month affair can hold a candle to that...",
          "Was it a two-year affair?", "And Nicole and Jeremy's affair was news to her.",
          "Well, I wondered at first, because he wouldn't sleep with me.",
          "I didn't sleep with her, but I did kiss her.",
          "He wanted the freedom to cheat on my sister."]


@pytest.mark.parametrize("line", CASTLE)
def test_caught(line):
    assert R.SLEEPING(w(line)), line
    assert R.old_sleeping_hit(w(line), False)
    assert E.sentence_hit("sleeping", w(line))            # CleanListen's too


@pytest.mark.parametrize("line", [
    "He cheated on his taxes.", "She cheated on the test.", "He cheated on Monday.",
    "Can I sleep with you tonight?", "That's my affair, not yours.", "It's a family affair.",
    "none of your affair", "It was no one's affair how lonely the day had been.",
    "Tut, tut, tut! that was the boy's affair.", "The sisters shared a room.",
])
def test_left_alone(line):
    assert not R.SLEEPING(w(line)), line


@pytest.mark.parametrize("line", [
    # the classics: someone's business, and two boys sharing a bed
    "But this being the Rajah's affair he did not resent it.",
    "Jerry refused to sleep with him because Carl had once taken a young garter snake to bed.",
    "And Nicole and Jeremy's affair was news to her.",
])
def test_not_in_an_older_book(line):
    assert not R.old_sleeping_hit(w(line), True), line
