"""CleanView 1.18.95's short-list phrases in the book apps (Castle S2E6; the owner, 2026-11-14:
"1 and 2", and words go to every app): sleeping with someone, "my lover", "sexiest"."""
import pytest

import cleanlisten as E
import cleanread as R
from conftest import words


def sexual(line):
    w = words(line)
    return [" ".join(w[i:j]) for i, j, cat in E.find_language(w, ["sexual"])]


MUTED = {
    "I'm not sleeping with her": "sleeping with her",
    "Are you sleeping with him?": "sleeping with him",
    "She was sleeping with someone else": "sleeping with someone",
    "I'm not sleeping with her now": "sleeping with her",
    "He slept with her last year": "slept with her",
    "she was sleeping with her in Paris": "sleeping with her",
    "he slept with her, and then he left": "slept with her",
    "He's sleeping with his boss": "sleeping with his boss",
    "She slept with her best friend": "slept with her best friend",
    "you were sleeping with my wife": "sleeping with my wife",
    "sleeping with their secretaries": "sleeping with their secretaries",
    "sleeping with her ex": "sleeping with her ex",
    "He was sleeping with a married woman": "sleeping with a married woman",
    "He was one of my lovers": "lovers",
    "her secret lover came back": "lover",
    "That is the sexiest thing I ever heard you say": "sexiest",
}
LEFT = ["She slept with her teddy bear", "the baby slept with her blanket",
        "He slept with his boots on",           # not a partner
        "a lover of books", "animal lovers everywhere", "Hey, lover, come here",
        "my love for you", "the lovers of music came"]


@pytest.mark.parametrize("line", MUTED)
def test_muted(line):
    assert sexual(line) == [MUTED[line]]


@pytest.mark.parametrize("line", LEFT)
def test_left_alone(line):
    assert sexual(line) == []


def test_a_new_sentence_after_her_counts():
    w = words("He slept with her She told me so")
    assert [" ".join(w[i:j]) for i, j, _ in E.find_language(w, ["sexual"])] == ["slept with her"]


def test_only_with_sexual_words_ticked():
    w = words("He was sleeping with his boss")
    assert E.find_language(w, ["swearing", "mild"]) == []


def test_cleanread_uses_the_same_lists():
    assert R.E is E                  # CleanRead (and ReadAloud) mark words with cleanlisten's lists
