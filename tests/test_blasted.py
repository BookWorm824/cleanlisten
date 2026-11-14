""""Blasted" and "blast it" are mild oaths in all three apps (the owner, 2026-11-14, of Poldark S1E1's
"lather and blasted brat", where only "brat" was muted: "Yes, add it"; CleanView 1.18.93's lines)."""
import pytest

import cleanlisten as E
import cleanread as R
import filters as F
from conftest import words

MUTED = ["lather and blasted brat", "Get that blasted dog out of my kitchen", "You blasted fool",
         "Turn off that blasted music", "Blast it, the horse has thrown a shoe", "Oh blast it all",
         "Blast you, Judd", "Blast and damnation", "Oh blast, I forgot the key"]
LEFT = ["The rocket blasted off at dawn", "They blasted through the rock", "He blasted the door open",
        "The cannon blasted the wall", "the music blasted from the speakers",
        "He got blasted at the party", "the town was blasted by the storm",
        "a blasted heath under the moon", "We had a blast at the fair",
        "Turn the radio up full blast", "The blast shook the windows", "a blast from the past",
        "Blast it open with the charge", "blast them out of the water", "Oh, what a blast"]


def minced(line):
    w = words(line)
    return [" ".join(w[i:j]) for i, j, cat in E.find_language(w, ["minced"])]


@pytest.mark.parametrize("line", MUTED)
def test_muted_as_a_mild_oath(line):
    got = minced(line)
    assert len(got) == 1 and "blast" in got[0], got


@pytest.mark.parametrize("line", LEFT)
def test_the_explosion_and_the_fun_are_left(line):
    assert minced(line) == []


def test_just_the_oath_is_muted_and_only_with_soft_swears_ticked():
    assert minced("lather and blasted brat") == ["blasted"]
    assert minced("Oh blast it all") == ["oh blast it"]
    assert minced("Blast and damnation") == ["blast and damnation"]
    assert E.find_language(words("You blasted fool"), ["mild", "moderate", "strong"]) == []
    assert E.listed_word("blasted", ["minced"]) and not E.listed_word("blasted", ["mild"])


def test_cleanread_marks_it_out(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Chapter 1\n\nGet that blasted dog out of my kitchen!\n\nThe rocket blasted off "
                 "at dawn.\n", encoding="utf8")
    book = R.Book(p)
    an = R.analyze(book, dict(F.PRESETS["young"]))
    assert [book.paras[m["para"]].text[m["a"]:m["b"]] for m in an["mutes"]] == ["blasted"]
    assert book.paras[an["mutes"][0]["para"]].text.startswith("Get that")
