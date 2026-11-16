"""In an older book, "queer" meaning strange (and "gay" meaning cheerful) is left alone: not marked
out and not even offered (the owner, 2026-11-16, of The Boxcar Children, where every "queer noise"
and "looked at Henry in a queer way" came up unticked: "yes leave alone in old books"). In a modern
book, and the modern meaning in any book, it is still found."""
import cleanread as R

OLD = ["The children heard a queer noise in the night.", "The doctor looked at Henry in a queer way.",
       "Henry did not like the queer noise at all.", "They ate bread and milk for supper.",
       "Watch the dog lay down by the fire.", "The cherries were red and ripe.",
       "She was gay and merry all the day long.", "Jessie swept the floor of the boxcar."]
MODERN = ["Sam told his parents he was gay.", "The queer community held a march downtown.",
          "They went to the store after school.", "Her phone buzzed on the table."]


def _book(tmp_path, lines, name):
    p = tmp_path / f"{name}.txt"
    p.write_text("\n\n".join(lines), encoding="utf8")
    return R.Book(str(p))


def _words(an):
    return [m["word_raw"].lower() for m in an["mutes"] if m["cat"] == "orientation"]


def test_older_meaning_left_alone_in_an_old_book(tmp_path):
    book = _book(tmp_path, OLD * 3, "old")
    assert book.old_style
    an = R.analyze(book, dict(samesexwords=True))
    assert _words(an) == []


def test_modern_meaning_still_found(tmp_path):
    book = _book(tmp_path, MODERN * 3, "modern")
    assert not book.old_style
    an = R.analyze(book, dict(samesexwords=True))
    assert "gay" in _words(an) and "queer" in _words(an)


def test_modern_meaning_in_an_old_book_still_found(tmp_path):
    book = _book(tmp_path, OLD * 3 + ["The gay rights march filled the street."], "mixed")
    assert book.old_style
    an = R.analyze(book, dict(samesexwords=True))
    assert _words(an) == ["gay"]
