"""Lessons from The Wind in the Willows (the night run's report, 2026-11-17, checked in the book): old
meanings in an older book, a friendly wink, a paw thrust in a pocket, trumpeters tooting."""
import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import MODERN, OLD, _book


def kinds(an):
    return [c["kind"] for c in an["cuts"]]


def test_old_meanings_and_a_wink_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD + [
        "Out of the centre of the pond rose a fanciful erection clothed in more cockleshells.",
        "He was humbled at the thought that both his popularity, and the sex that seemed to inspire it, were another's.",
        "He would probably have been aroused much earlier, had he not slept on straw.",
        "Rather! replied the Otter, winking at the Mole.",
        "Then, as he looked, it winked at him, and so declared itself to be an eye.",
        "Toad straddled on the hearthrug, thrust his paw into his trouser-pocket and pulled out silver.",
        "The affair was soon over."], "old_willows")
    assert book.old_style
    an = R.analyze(book, dict(sexual=True, refs=True, flirt=True, relationships=True, sleeping=True))
    assert an["mutes"] == []
    assert kinds(an) == []


def test_the_real_thing(tmp_path):
    book = _book(tmp_path, MODERN + ["He had an erection.", "She winked at him and leaned closer, flirting."], "modern_w")
    an = R.analyze(book, dict(sexual=True, refs=True, flirt=True))
    assert [m["word_raw"] for m in an["mutes"]] == ["erection"]
    assert "flirt" in kinds(an)


def test_trumpeters_tooting():
    assert not E.crude_hit(words("The trumpeters are tooting and the soldiers are saluting"))
