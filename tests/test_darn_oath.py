"""Anne of the Island's "Darn her," exploded Davy is the oath; "darn her stockings" is sewing (re-check of the
free classics, 2026-11-19)."""
import pytest

import cleanlisten as E


def found(text, breaks=()):
    ws = [w for w in (E.norm(t) for t in text.split()) if w]
    return [" ".join(ws[i:j]) for i, j, _ in E.find_language(ws, ["minced"], breaks=breaks)]


@pytest.mark.parametrize("text", ["Darn her, exploded Davy.", "Oh, darn it", "darn you, said Tom"])
def test_the_oath(text):
    assert found(text), text


@pytest.mark.parametrize("text", ["She sat down to darn her stockings.", "He had to darn his socks.",
                                  "Abigail would darn the elbows."])
def test_sewing(text):
    assert not found(text), text


def test_end_of_sentence():
    assert found("Darn her. She took it.", breaks={2})
