"""From the owner's first-chapters report (2026-11-15, Jane Eyre and Hugo; "Yes, both"): "in the
raw twilight" isn't nudity, and one explicit word ("naked isles", "passed its climax") isn't a
sexual reference on its own any more, as in CleanRead."""
import pytest

import cleanlisten as E
from test_smoke import _book, _ffmpeg


def words(text):
    return [w for w in (E.norm(t) for t in text.split()) if w]


@pytest.mark.parametrize("text", [
    "Dreadful to me was the coming home in the raw twilight with nipped fingers and toes.",
    "We walked home in the raw cold of a February morning.",
    "They worked in the raw wind off the moor.",
])
def test_raw_weather_is_not_nudity(text):
    assert not E.sentence_hit("nudity", words(text))


@pytest.mark.parametrize("text", ["He likes to sleep in the raw.", "They went swimming in the raw.",
                                  "She was stark naked.", "He stood there in the buff."])
def test_naked_still_nudity(text):
    assert E.sentence_hit("nudity", words(text))


def test_two_explicit_words():
    assert not E.two_explicit(words("the naked, melancholy isles of farthest Thule"))
    assert not E.two_explicit(words("My terror had passed its climax."))
    assert E.two_explicit(words("She lay naked, moaning with pleasure."))


@pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")
def test_one_explicit_word_is_not_a_reference(tmp_path):
    script = [(0.5, "Round the naked, melancholy isles the surge pours in."),
              (5.0, "My terror had passed its climax."),
              (9.0, "Then everyone went home.")]
    audio, work, _ = _book(tmp_path, script)
    st = E.analyze([audio], work, groups=("sexual",), find_refs=True, log=lambda *a: None)
    assert st["scenes"] == []


@pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")
def test_two_explicit_words_still_a_reference(tmp_path):
    script = [(0.5, "It was late."), (4.0, "She lay naked, moaning with pleasure."), (9.0, "Then they slept.")]
    audio, work, _ = _book(tmp_path, script)
    st = E.analyze([audio], work, groups=("sexual",), find_refs=True, log=lambda *a: None)
    assert [sc["text"] for sc in st["scenes"]] == [script[1][1]]
