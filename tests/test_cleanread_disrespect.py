"""CleanRead's clean copy: the Disrespect filter (shared with CleanListen and CleanView)."""
import pytest

import cleanread as R

BOOK = """Chapter One

Mom asked Sam to clean his room.

"You're not the boss of me!" Sam shouted.

They had pancakes for dinner.
"""


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LEARNED", tmp_path / "cleanread_learned.json")
    p = tmp_path / "book.txt"
    p.write_text(BOOK, encoding="utf8")
    return R.Book(str(p))


def test_disrespect_is_cut_only_when_ticked(book):
    assert [c for c in R.analyze(book, {"kiss": "keep"})["cuts"] if c["kind"] == "disrespect"] == []
    cuts = [c for c in R.analyze(book, {"kiss": "keep", "disrespect": True})["cuts"]
            if c["kind"] == "disrespect"]
    assert len(cuts) == 1 and "boss of me" in cuts[0]["text"]
    assert R.CLEAN_LABELS["disrespect"] == "Disrespect" and "disrespect" in R.CLEAN_AI
