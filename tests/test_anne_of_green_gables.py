"""Lessons from Anne of Green Gables (the night run's report, 2026-11-17, checked in the book), and a
guard against a word being listed twice in the exception lists (a second entry silently replaces the
first: it hid the "ain't dumb" and "gray sod" lessons)."""
import ast
import pathlib

import pytest

import cleanlisten as E
import cleanread as R
from conftest import words
from test_old_words_and_gump import OLD, _book

CATS = list(E.ALL_CATS) + ["rude"]


def found(text):
    ws = words(text)
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, CATS)]


def kinds(an):
    return [c["kind"] for c in an["cuts"]]


def test_no_word_listed_twice():
    src = pathlib.Path(E.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("INNOCENT_NEXT", "INNOCENT_PREV")
                                                for t in node.targets) and isinstance(node.value, ast.Dict):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            assert len(keys) == len(set(keys)), sorted({k for k in keys if keys.count(k) > 1})


def test_words():
    assert found("if people wouldn't twit me about my looks") == []
    assert found("a stir of hidden pulses under the gray sod") == []
    assert found("a chromo entitled, Christ Blessing Little Children") == []
    assert found("You lucky sod!") and found("Oh, Christ, not again!")


def test_old_book(tmp_path):
    book = _book(tmp_path, OLD + [
        "the affection born of long intercourse for their good old minister",
        "Anne dear, would you like to have me sleep with you tonight?",
        "I might have let her spend the night with Diana, if that was all.",
        "Diana and I are promising each other that we will never marry but be nice old maids and live together forever.",
        "everything seems to be calling to me, Anne, Anne, come out to us."], "old_anne")
    assert book.old_style
    an = R.analyze(book, dict(sexual=True, refs=True, unmarried=True, relationships=True))
    assert an["mutes"] == [] and kinds(an) == []


@pytest.mark.parametrize("text", ["Matthew slapped the reins on the sorrel's back delightedly.",
                                  "Then Mr. Thomas was killed falling under a train.",
                                  "You'll fall off and be killed.", "Anne, are you killed? shrieked Diana.",
                                  "No, Diana, I am not killed.", "Then Diana puts too many murders into hers.",
                                  "It was silly to be writing about love and murder and elopements.",
                                  "You needn't rush to any extreme of killing yourself over your books."])
def test_not_violence(text):
    assert not R.VIOLENCE(words(text)), text


def test_bullying():
    assert not E.bully_hit(words("I'm awful sorry I made fun of your hair, Anne, he whispered."))
    assert not E.bully_hit(words("Anne Shirley, you'll kill yourself."))
    assert E.bully_hit(words("They made fun of her hair every day."))


def test_violence_still_found():
    assert R.VIOLENCE(words("The robber murdered the old man."))
    assert R.VIOLENCE(words("He killed her in the night."))


def test_heidi(tmp_path):
    """Heidi (the night run's report, 2026-11-17): the pillows, and a beam that fell (an accident)."""
    book = _book(tmp_path, OLD + ["Then you can sleep soft on the down from them.",
                                  "Could you sleep with them, grandmother?"], "old_heidi")
    an = R.analyze(book, dict(sexual=True, refs=True))
    assert an["mutes"] == [] and kinds(an) == []
    assert not R.VIOLENCE(words("a beam fell on him and killed him"))
