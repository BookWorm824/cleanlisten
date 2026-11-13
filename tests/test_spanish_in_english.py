"""A short list of Spanish swear words on the English lists, for Spanish said in a mostly English
book (CleanView 1.18.86; the owner there, 2026-11-13: "would loading spanish known swear words into
the english filter help without using a separate filter?", "add the short list and we will look at
the other option later")."""
import pytest

import cleanlisten as E
import cleanread as R
import filters as F

CATCH = [("Shut up, pendejo.", "pendejo"), ("That cabrón took my truck.", "cabrn"),
         ("¡Puta madre!", "puta"), ("Those putos never paid.", "putos"),
         ("Joder, not again.", "joder"), ("Jódete, amigo.", "jdete"),
         ("He's a jodido liar.", "jodido"), ("Vete al carajo.", "carajo"),
         ("What a gilipollas.", "gilipollas"), ("Chinga tu madre.", "chinga"),
         ("The chingada truck broke down.", "chingada"), ("Hijueputa!", "hijueputa"),
         ("Two cabrones walked in.", "cabrones"), ("Pendejas, all of them.", "pendejas")]
LEAVE = ["The dove's soft coo woke her up.", "We ordered chili con carne for the table.",
         "Mrs. Concha Ortiz teaches third grade.", "Mr. Ching and Mrs. Chang arrived at noon.",
         "The computer was put away for the night.", "The carbon fiber layup is on page nine.",
         "Jody and Jodie joined the choir.", "A Puerto Rican flag hung over the door.",
         "She ate the pollo with rice.", "He put a carton of eggs in the cart."]


def words(s):
    return [E.norm(t) for t in s.split() if E.norm(t)]


@pytest.mark.parametrize("line, word", CATCH)
def test_caught_as_swearing(line, word):
    w = words(line)
    assert [(w[i], cat) for i, j, cat in E.find_language(w, ["moderate"])] == [(word, "moderate")]
    assert E.find_language(w, ["mild", "minced", "deity"]) == []        # swearing's box only


@pytest.mark.parametrize("line", LEAVE)
def test_everyday_look_alikes_are_left(line):
    assert E.find_language(words(line), E.ALL_CATS + ["rude"]) == []


def test_the_slur_is_with_the_same_sex_words():
    w = words("He called him a maricón in front of everyone.")
    assert [(w[i], cat) for i, j, cat in E.find_language(w, ["orientation"])] == [
        ("maricn", "orientation")]
    assert E.find_language(words("Los maricones"), ["orientation"])
    assert E.find_language(w, ["moderate"]) == []


def test_cleanread_marks_them_out_in_an_english_book(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Chapter 1\n\nThat cabrón took my truck, the pendejo.\n\nWe ordered chili con "
                 "carne and put the carbon paper away.\n", encoding="utf8")
    book = R.Book(p)
    an = R.analyze(book, dict(F.PRESETS["young"]))
    hit = [book.paras[m["para"]].text[m["a"]:m["b"]] for m in an["mutes"]]
    assert hit == ["cabrón", "pendejo"]
