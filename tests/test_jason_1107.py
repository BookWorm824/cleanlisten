"""Jason's requests of 2026-11-07 (via the owner and CleanView): CleanRead's filters on its main
page, the chat told who does what, the logo in the empty space, and a findings spreadsheet of
just the book being reviewed."""
import csv
import json
import os
import tkinter as tk
from pathlib import Path

import pytest

import filters as F
import logo as LOGO

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def _tk():
    # one window for the file. Right after another test's window, Tcl on Windows sometimes
    # can't start ("invalid command name tcl_findLibrary"); a second try works
    for n in range(5):
        try:
            r = tk.Tk()
            break
        except tk.TclError:
            if n == 4:
                raise
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def root(_tk, tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "OLD_CLEANREAD", tmp_path / "none.json")
    monkeypatch.setattr(F, "APP_DATA", tmp_path)
    yield _tk
    for w in _tk.winfo_children():
        w.destroy()


def _saved(tmp_path):
    return json.loads((tmp_path / "filters.json").read_text(encoding="utf8"))


def test_the_panel_shows_every_box_and_keeps_changes_at_once(root, tmp_path):
    host = tk.Frame(root)
    host.pack()
    p = F.FilterPanel(host)
    assert set(p.vars) >= set(F.BOXES) | set(F.LEVELS)
    assert p.profile.get() == "adults"
    assert p.ticks()["gore"] is True and p.ticks()["violence"] is False
    p.vars["violence"].set(True)
    assert _saved(tmp_path)["ticks"]["adults"]["violence"] is True
    p.vars["kiss"].set("Cut all kisses")
    assert _saved(tmp_path)["ticks"]["adults"]["kiss"] == "all"
    assert p.ticks()["kiss"] == "all"
    p.words.insert("1.0", "grow some stones\n")
    assert p.mywords() == ["grow some stones"]
    assert _saved(tmp_path)["mywords"] == ["grow some stones"]


def test_each_age_has_its_own_ticks(root, tmp_path):
    host = tk.Frame(root)
    p = F.FilterPanel(host)
    p.vars["violence"].set(True)
    p.profile.set("young")
    p._profile_changed()
    assert _saved(tmp_path)["profile"] == "young"
    assert p.vars["rude"].get() is True                    # young kids' standard ticks
    p.vars["rude"].set(False)
    p.profile.set("adults")
    p._profile_changed()
    assert p.vars["violence"].get() is True and p.vars["rude"].get() is False
    assert _saved(tmp_path)["ticks"]["young"]["rude"] is False
    assert "Adults" in p.std.cget("text")


def test_back_to_the_standard_ticks(root, tmp_path):
    p = F.FilterPanel(tk.Frame(root))
    p.vars["gore"].set(False)
    p.vars["smoking"].set(True)
    p.standard()
    assert p.ticks()["gore"] is True and p.ticks()["smoking"] is False
    assert _saved(tmp_path)["ticks"]["adults"]["gore"] is True


def test_cleanlistens_window_still_works_and_shows_the_same_ticks(root, tmp_path):
    p = F.FilterPanel(tk.Frame(root))
    p.vars["drugs"].set(True)
    d = F.load()
    done = []
    w = F.FiltersWindow(root, d, lambda: done.append(1))
    assert w.vars["drugs"].get() is True
    w.vars["smoking"].set(True)
    w._done()
    assert done and d["ticks"]["adults"]["smoking"] is True and d["ticks"]["adults"]["drugs"] is True


def test_cleanread_shows_the_boxes_on_its_page():
    src = (REPO / "CleanRead.pyw").read_text(encoding="utf8")
    assert "F.FilterPanel(b3" in src and "F.FilterCard(" not in src
    assert "Choose filters" not in src
    # CleanListen keeps its window for now
    assert "F.FilterCard(b3" in (REPO / "CleanListen.pyw").read_text(encoding="utf8")


class _CC:
    @staticmethod
    def saved_provider():
        return "gemini"

    @staticmethod
    def name(p):
        return {"gemini": "Gemini"}[p]

    @staticmethod
    def rules_text(d):
        return "(rules)"


def test_the_chat_knows_who_does_what():
    import cleanread as R
    text = R.how_it_works(_CC)
    assert "You (Gemini) are only this chat" in text
    assert "Ollama" in text and "It is not you" in text and "word lists" in text
    assert "{" not in text
    assert R.how_it_works(None).count("the AI in this chat") == 1

    class FakeBook:
        sents = []
    chat = R.CheckChat.__new__(R.CheckChat)
    assert R.HOW_IT_WORKS.splitlines()[0] in chat._system(_CC)
    clean = R.Chat.__new__(R.Chat)
    clean.an = {"opts": {"swearing": True, "sex": True}}
    sysmsg = clean._system(_CC)
    assert "You (Gemini) are only this chat" in sysmsg and "(rules)" in sysmsg


@pytest.mark.parametrize("ico", ["icon.ico", "cleanread.ico", "readaloud.ico"])
def test_the_logo_is_about_128_wide(root, ico):
    img = LOGO.logo_image(ico, 128)
    assert img is not None and 100 <= img.width() <= 160, (ico, img and img.width())
    lbl = LOGO.put_logo(root, ico, "#F6F3EE")
    assert lbl is not None and lbl.image is not None


def test_no_logo_without_a_picture(root):
    assert LOGO.logo_image("no such.ico") is None
    assert LOGO.put_logo(root, "no such.ico", "#F6F3EE") is None


def test_the_progress_pages_show_the_logo_and_logo_py_is_shipped():
    assert "logo.py" in json.loads((REPO / "version.json").read_text())["files"]
    assert 'LOGO.put_logo(p, "icon.ico", BG)' in (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert (REPO / "CleanRead.pyw").read_text(encoding="utf8").count('LOGO.put_logo(p, "cleanread.ico", BG)') == 2


def test_a_spreadsheet_of_just_this_book_and_every_book_newest_first(tmp_path, monkeypatch):
    import cleanlisten_learn as L
    monkeypatch.setattr(L, "FINDINGS", tmp_path / "f")
    monkeypatch.setattr(L, "CSV_PATH", tmp_path / "all.csv")
    (tmp_path / "f").mkdir()
    for book, day in (("Old Book", "2026-10-01"), ("New Book", "2026-11-07"), ("Mid Book", "2026-10-20")):
        (tmp_path / "f" / f"{book}.json").write_text(json.dumps(
            {"book": book, "date": day, "reviewer": "Claude",
             "rows": [["Part 1 0:00:01", "word", "mild", "a [damn]", "remove", "", "why"]]}))
    L.write_all_csv()
    rows = list(csv.reader(open(tmp_path / "all.csv", encoding="utf-8-sig")))
    assert rows[0] == L.CSV_HEAD
    assert [r[1] for r in rows[1:]] == ["New Book", "Mid Book", "Old Book"]
    one = L.book_csv("Mid Book")
    rows = list(csv.reader(open(one, encoding="utf-8-sig")))
    assert [r[1] for r in rows[1:]] == ["Mid Book"]
    assert L.book_csv("Never Checked") is None


def test_cleanlisten_offers_both_spreadsheets():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert "findings for this book (spreadsheet)" in src and "findings for every book (spreadsheet)" in src
    assert "learn.book_csv(" in src
