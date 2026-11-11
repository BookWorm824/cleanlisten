"""A lone "the affair" / "an affair" is sleeping around, in CleanRead and CleanListen, as in
CleanView 1.18.51 (Lauren's Castle S1E5: "How long was the affair?" wasn't caught). The owner,
2026-11-09: "add it to the next update"."""
import pytest

import cleanlisten as E
import cleanread as R

CATCH = ["How long was the affair?", "Please. No one ends an affair",
         "They have a fight. About the affair.", "I had a love affair with her",
         "his affair with the nanny", "Their affair lasted two years.",
         "They end an affair because they're scared."]
LEAVE = ["Internal Affairs is here.", "That is none of your affair.", "It's my affair, not yours.",
         "The wedding was quite an affair.", "What an affair that was!", "It was a black-tie affair.",
         "It's a family affair.", "the affair of the diamond necklace", "foreign affairs",
         "She put her affairs in order.", "the current state of affairs", "Such an affair it was."]


def words(s):
    return [R.nrm(t) for t in s.split() if R.nrm(t)]


@pytest.mark.parametrize("line", CATCH)
def test_caught(line):
    assert R.SLEEPING(words(line)) and E.sleeping_hit(words(line))


@pytest.mark.parametrize("line", LEAVE)
def test_left_alone(line):
    assert not R.SLEEPING(words(line)) and not E.sleeping_hit(words(line))
