"""Lessons from Pollyanna (the night run's report, 2026-11-17, checked in the book): 1913 courtship
words, a lonely child wanting someone near at night, and a child undressing for bed, all in an older
book. Modern books and the real thing are unchanged."""
import cleanread as R
from test_old_words_and_gump import MODERN, OLD, _book


def kinds(an):
    return [c["kind"] for c in an["cuts"]]


OPTS = dict(sexual=True, refs=True, sleeping=True, implied=True)


def test_courtship_and_bedtime_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + [
        "It was Miss Polly's love affair, they said, years ago.",
        "Because you were lovers, you know, once.",
        "Nancy wondered about the trouble with her lover, and who was her lover?",
        "And when I've so wanted to sleep with someone sometime, someone that belonged to me.",
        "She undressed, folded her clothes neatly, and said her prayers.",
        "Then she was undressed tenderly and put to bed."], "old_polly")
    assert book.old_style
    an = R.analyze(book, OPTS)
    assert an["mutes"] == []
    assert [k for k in kinds(an) if k in ("sleeping", "ref", "implied")] == []


def test_the_real_thing_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + ["He kept a mistress in town, and his wife knew of the adultery.",
                                  "She undressed and lay down beside him."], "old_real")
    assert book.old_style
    an = R.analyze(book, OPTS)
    assert "sleeping" in kinds(an) and "implied" in kinds(an)


def test_modern_books_unchanged(tmp_path):
    book = _book(tmp_path, MODERN + ["She was having an affair with her boss.", "He met her lover at the bar.",
                                     "I want to sleep with someone tonight, she said."], "modern_polly")
    assert not book.old_style
    an = R.analyze(book, OPTS)
    assert "sleeping" in kinds(an)
    assert {m["word_raw"].lower() for m in an["mutes"]} >= {"lover", "sleep with someone"}
