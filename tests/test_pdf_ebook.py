"""CleanRead's PDF -> ebook (1.17.74; the owner, 2026-11-19: "I have some old books that are pdfs but
its more just like images saved in a pdf, so isn't really optimized for reading").

- build(): page numbers and running heads go, lines join into paragraphs, a word split at a line end
  is mended, chapters are found (a "Chapter" line, a lone number, a lowered first line on a page
  with no running head) and numbered in order.
- a real picture-only PDF, made here by drawing pages of text and keeping only their pictures, is
  read with Windows' own text recognition and comes out as an EPUB CleanRead opens with chapters.
- the window: a PDF shows "Make an ebook"; a PDF with text is checked as it always was; the
  ready page shows a sample and leads on to checking or cleaning the ebook.
"""
import ctypes
import importlib.machinery
import importlib.util
import json
import os
import zipfile
from pathlib import Path

import pytest

from conftest import REPO
import pdfbook


# ---------------------------------------------------------------------------------------------
# made-up pages of rows (what a page gives once read), for the book-building rules
# ---------------------------------------------------------------------------------------------
W, H, L, R, PITCH, HGT = 300.0, 500.0, 20.0, 280.0, 14.0, 10.0


def row(t, y, x0=L, x1=R, h=HGT):
    return {"t": t, "x0": x0, "x1": x1, "y0": y, "y1": y + h, "h": h}


def page(i, lines, head=True, start=50.0, title="THE TEST BOOK"):
    """lines: (text, kind) with kind "full", "indent", "last" (short last line), "indent-last"."""
    rows = []
    if head:
        rows.append(row(f"{i + 1} {title}" if i % 2 else f"{title} {i + 1}", 20, 100, 200, 8))
    y = start
    for t, kind in lines:
        x0 = L + 15 if kind.startswith("indent") else L
        x1 = 150 if kind.endswith("last") else R
        rows.append(row(t, y, x0, x1))
        y += PITCH
    return {"i": i, "w": W, "h": H, "src": "ocr", "pic": True, "rows": rows}


FILL = "and the long road went on and on past the farm and the mill"     # a full line of print


def story():
    p = []
    # 0: title page (no head), 1: chapter one opens lower down with "CHAPTER ONE"
    p.append({"i": 0, "w": W, "h": H, "src": "ocr", "pic": True,
              "rows": [row("THE TEST BOOK", 120, 60, 240, 30), row("Jane Writer", 200, 100, 200, 16)]})
    p.append(page(1, [("CHAPTER ONE", "centre")] + [("It was a cold morning when Anna left the old", "indent"),
                                                     (FILL, "full"), ("farm for the town.", "last"),
                                                     ("She walked a long way and saw the ques-", "indent"),
                                                     ("tions in every face along the road to the", "full"),
                                                     (FILL, "full")], head=False, start=200))
    p[1]["rows"][0].update(x0=110, x1=190)
    for i in range(2, 6):
        p.append(page(i, [(FILL, "full"), (FILL, "full"), ("and so the day went by.", "last"),
                          ("Then a new thing came along the road at", "indent"), (FILL, "full"),
                          (FILL, "full"), (FILL, "full")]))
    # 6: chapter two opens lower down with no heading at all (old scans often lose the number)
    p.append(page(6, [("The next week brought rain to the valley and", "indent"), (FILL, "full"),
                      (FILL, "full"), ("and the river rose.", "last")], head=False, start=220))
    for i in range(7, 10):
        p.append(page(i, [(FILL, "full"), (FILL, "full"), ("and that was all.", "last")]))
    return p


def test_book_from_pages():
    info = {}
    secs = pdfbook.build(story(), info=info)
    front = [s for s in secs if s["front"]]
    chapters = [s for s in secs if not s["front"]]
    assert [s["title"] for s in chapters] == ["Chapter 1", "Chapter 2"]
    assert front and any("THE TEST BOOK" in t for _, t in front[0]["paras"])
    text = " ".join(t for s in secs for _, t in s["paras"])
    assert "TEST BOOK 3" not in text and "4 THE TEST BOOK" not in text       # running heads gone
    first = chapters[0]["paras"]
    assert first[0] == ["p", "It was a cold morning when Anna left the old " + FILL + " farm for the town."]
    assert "the questions in every face" in first[1][1]                     # "ques-" "tions" mended
    assert chapters[1]["paras"][0][1].startswith("The next week brought rain")
    assert info["heads"].get("THE TEST BOOK", 0) >= 4


def test_title_and_author_from_the_pages():
    pages = story()
    info = {}
    pdfbook.build(pages, info=info)
    assert pdfbook._from_pages(pages, info, "scan0001.pdf") == ("The Test Book", "Jane Writer")


def test_line_end_words():
    join = pdfbook._joiner({"questions": 2, "twenty-five": 1, "town": 5, "the": 9, "self": 3})
    assert join("the ques-", "tions were") == "the questions were"
    assert join("she was twenty-", "five then") == "she was twenty-five then"
    assert join("a self-", "forgetful man") == "a self-forgetful man"
    assert join("him—", "wasn't there") == "him—wasn't there"
    # the Internet Archive's hidden text drops the hyphen: "town un" "doubtedly"
    assert join("in his gambling town un", "doubtedly to", full=True) == "in his gambling town undoubtedly to"
    assert join("down the", "road", full=True) == "down the road"
    assert join("down the un", "road") == "down the un road"         # not a full line: left alone


def test_tidy_and_specks():
    assert pdfbook._tidy_text("hard on us all —pretty  shat") == "hard on us all—pretty shat"
    assert pdfbook._junk("H)LL/SAJVH/TNEY")
    assert pdfbook._junk("llllllllllllillll")
    assert not pdfbook._junk("* * *")
    assert not pdfbook._junk("\"I'll manage,\" I said.")


def test_names():
    assert pdfbook._clean_author("Whitney, Phyllis A., 1903-2008") == "Phyllis A. Whitney"
    assert pdfbook._clean_title("A candle in her heart", "x.pdf") == "A Candle in Her Heart"
    assert pdfbook._clean_title("", "My_Old_Book.pdf") == "My Old Book"


def test_epub_opens_in_cleanread(tmp_path):
    import cleanread
    secs = pdfbook.build(story())
    out = pdfbook.write_epub(tmp_path / "t.epub", "The Test Book", "Jane Writer", secs,
                             description="A test.")
    z = zipfile.ZipFile(out)
    assert z.namelist()[0] == "mimetype"
    book = cleanread.Book(out)
    assert book.title == "The Test Book" and book.author == "Jane Writer"
    assert "Chapter 1" in book.chapters and "Chapter 2" in book.chapters
    assert any("questions in every face" in p.text for p in book.paras)


# ---------------------------------------------------------------------------------------------
# a real picture-only PDF, read by Windows
# ---------------------------------------------------------------------------------------------
TEXT_PAGES = [
    ["CHAPTER ONE", "", "    Mary lived in a small white house at the edge",
     "of the woods with her grandmother and a gray",
     "cat named Pepper. Every morning she carried the",
     "milk pail down the hill to the neighbor's barn.",
     "    One cold morning the barn door stood open and",
     "the cows were gone. Mary looked all around the",
     "yard, but there was nothing to see except the",
     "tracks of a wagon going toward the river road."],
    ["She ran back up the hill to tell her grandmother,",
     "who put on her shawl and came out to look. They",
     "followed the tracks together until they reached",
     "the old stone bridge, where a boy was sitting on",
     "the wall with a long switch in his hand.",
     "    \"Have you seen our cows?\" Mary asked him.",
     "    \"They went that way,\" he said, and pointed to",
     "the meadow on the far side of the water."],
    ["CHAPTER TWO", "", "    The meadow was wide and green, and the cows",
     "were standing in the tall grass by the fence. Mary",
     "laughed when she saw them, because Pepper the cat",
     "had followed her all the way from the house and",
     "was sitting on the gate as if she owned it."],
]


def _text_pdf(path, pages):
    """A PDF of typed pages (Times, 11 point) with a running head and page number on each."""
    pdfium = pytest.importorskip("pypdfium2")
    raw = pdfium.raw
    doc = pdfium.PdfDocument.new()

    def put(pg, text, x, y, size=11.0):
        obj = raw.FPDFPageObj_NewTextObj(doc.raw, b"Times-Roman", ctypes.c_float(size))
        buf = ctypes.create_unicode_buffer(text)
        raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
        raw.FPDFPage_InsertObject(pg.raw, obj)

    for n, lines in enumerate(pages):
        pg = doc.new_page(320, 460)
        if not lines[0].startswith("CHAPTER"):
            put(pg, f"MARY AND THE COWS  {n + 1}", 110, 430, 9)
        y = 400 if not lines[0].startswith("CHAPTER") else 330
        for line in lines:
            if line.startswith("CHAPTER"):
                put(pg, line, 120, y, 14)
            elif line:
                put(pg, line.strip(), 40 if line.startswith("    ") else 25, y)
            y -= 16
        put(pg, str(n + 1), 155, 30, 9) if lines[0].startswith("CHAPTER") else None
        raw.FPDFPage_GenerateContent(pg.raw)
    doc.save(str(path))


def _pictures_only(src, dst):
    pdfium = pytest.importorskip("pypdfium2")
    a = pdfium.PdfDocument(str(src))
    b = pdfium.PdfDocument.new()
    for i in range(len(a)):
        w, h = a[i].get_size()
        img = pdfium.PdfImage.new(b)
        img.set_bitmap(a[i].render(scale=3, grayscale=True))
        img.set_matrix(pdfium.PdfMatrix().scale(w, h))
        pg = b.new_page(w, h)
        pg.insert_obj(img)
        pg.gen_content()
    b.save(str(dst))


@pytest.mark.skipif(os.name != "nt", reason="Windows' own text recognition")
def test_a_scanned_pdf_becomes_an_ebook(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfbook, "WORK", tmp_path / "work")
    typed, scanned = tmp_path / "typed.pdf", tmp_path / "Mary and the Cows.pdf"
    _text_pdf(typed, TEXT_PAGES)
    _pictures_only(typed, scanned)
    assert pdfbook.kind(scanned) == "pictures" and pdfbook.kind(typed) == "text"
    said = []
    res = pdfbook.convert(scanned, progress=lambda f, m: said.append((f, m)))
    assert res["read_pages"] == 3 and res["chapters"] == 2
    assert any("Reading the words on page" in m for _, m in said) and said[-1][0] == 1.0
    import cleanread
    book = cleanread.Book(res["out"])
    text = " ".join(p.text for p in book.paras)
    assert "Mary lived in a small white house at the edge of the woods" in text
    assert "MARY AND THE COWS" not in text                               # the running head
    assert "Chapter 1" in book.chapters and "Chapter 2" in book.chapters
    # read again: every page is kept, so it's quick and the same
    again = pdfbook.convert(scanned)
    assert again["paras"] == res["paras"]


@pytest.mark.skipif(os.name != "nt", reason="Windows' own text recognition")
def test_cancel_stops_the_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfbook, "WORK", tmp_path / "work")
    typed, scanned = tmp_path / "typed.pdf", tmp_path / "scan.pdf"
    _text_pdf(typed, TEXT_PAGES)
    _pictures_only(typed, scanned)
    seen = []

    def cancel():
        return len(seen) >= 1
    with pytest.raises(pdfbook.Stopped):
        pdfbook.convert(scanned, progress=lambda f, m: seen.append(m) if "page" in m else None, cancel=cancel)
    kept = list((tmp_path / "work").glob("*/pages.jsonl"))
    assert kept and 1 <= len(kept[0].read_text().splitlines()) < 3      # carries on from there next time


def test_locked_or_missing_pdf_says_so_plainly(tmp_path):
    with pytest.raises(pdfbook.ConvertError, match="wasn't found"):
        pdfbook.convert(tmp_path / "nope.pdf")


# ---------------------------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------------------------
def load_ui():
    loader = importlib.machinery.SourceFileLoader("cr_pdf_ebook", str(REPO / "CleanRead.pyw"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def window():
    """One hidden window for these tests (Tk on Windows can fail to start a second time in one run)."""
    import tkinter as tk
    ui = load_ui()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ui, "chime", lambda: None)
        mp.setattr(ui.freezes.Watch, "offer", lambda self: None, raising=False)
        try:
            a = ui.App()
        except tk.TclError as ex:
            pytest.skip(f"no display ({ex})")
        a.withdraw()
        yield ui, a
        a.destroy()


@pytest.fixture
def app(window):
    ui, a = window
    a.book_path, a.book, a.pdf_kinds = None, None, {}
    a.show_setup()
    return ui, a


def _texts(w):
    out = []
    for c in w.winfo_children():
        try:
            out.append(str(c.cget("text")))
        except Exception:
            pass
        out.extend(_texts(c))
    return out


def test_a_pdf_offers_make_an_ebook(app, tmp_path):
    ui, a = app
    a.book_path = str(tmp_path / "Old Book.pdf")
    a._pdf_kinds()[a.book_path] = "pictures"
    a._refresh()
    words = " ".join(_texts(a.pdf_box))
    assert "This PDF is pictures of pages" in words
    a.book_path = str(tmp_path / "Book.epub")
    a._refresh()
    assert "Make it an ebook" in " ".join(_texts(a.pdf_box))


def test_ready_page_shows_a_sample_and_goes_on(app, tmp_path):
    ui, a = app
    res = {"out": str(tmp_path / "Old Book.epub"), "title": "Old Book", "author": "", "pages": 120,
           "read_pages": 118, "chapters": 9, "paras": 900, "first_chapter": "Chapter 1",
           "sample": ["It was a dark and stormy night.", "The rain fell."], "seconds": 40}
    a._handle(("ebook_made", res))
    words = " ".join(_texts(a.page))
    assert "Your ebook is ready" in words and "It was a dark and stormy night." in words
    assert a.book_path == res["out"]              # "Check or clean it" goes on with the ebook


def test_a_pdf_with_text_is_checked_as_before(app, monkeypatch, tmp_path):
    ui, a = app
    called = []
    monkeypatch.setattr(pdfbook, "kind", lambda p: "text")
    monkeypatch.setattr(pdfbook, "convert", lambda *x, **k: called.append(1))
    path = str(tmp_path / "Book.pdf")
    assert a._as_ebook(a.job, path, lambda m: None) == path and not called
    monkeypatch.setattr(pdfbook, "kind", lambda p: "pictures")
    a.pdf_kinds = {}
    sent = []
    monkeypatch.setattr(pdfbook, "convert", lambda *x, **k: {"out": str(tmp_path / "Book.epub"), "title": "B"})
    assert a._as_ebook(a.job, path, sent.append) == str(tmp_path / "Book.epub")
    assert sent[-1][0] == "converted"


def test_version_lists_the_new_file():
    files = json.loads((REPO / "version.json").read_text())["files"]
    assert "pdfbook.py" in files


# ---------------------------------------------------------------------------------------------
# pictures of the pages (1.17.75; the owner: "it needs to be able to do the same with jpegs or
# pngs...I have some old books I scanned")
# ---------------------------------------------------------------------------------------------
def _page_pictures(folder, turn_second=True):
    """The typed pages as PNG pictures named "Page 9", "Page 10", "Page 11" (name order isn't
    letter order), the second one scanned sideways."""
    import numpy as np
    pdfium = pytest.importorskip("pypdfium2")
    typed = folder.parent / "typed_for_pictures.pdf"
    _text_pdf(typed, TEXT_PAGES)
    doc = pdfium.PdfDocument(str(typed))
    folder.mkdir()
    for n in range(len(doc)):
        a = doc[n].render(scale=4, grayscale=True).to_numpy()
        a = a[:, :, 0] if a.ndim == 3 else a
        if n == 1 and turn_second:
            a = np.rot90(a)                        # a quarter turn left
        pdfbook.write_png(folder / f"Page {n + 9}.png", a)
    return sorted(folder.iterdir())


def test_picture_order_and_names(tmp_path):
    folder = tmp_path / "Grandma's Cows"
    folder.mkdir()
    for n in (10, 9, 11):
        (folder / f"Page {n}.jpg").write_bytes(b"x")
    (folder / "notes.txt").write_text("not a page")
    assert [f.name for f in pdfbook.pictures_in(folder)] == ["Page 9.jpg", "Page 10.jpg", "Page 11.jpg"]
    assert pdfbook._pictures_title(pdfbook.pictures_in(folder)) == "Grandma's Cows"
    plain = tmp_path / "Downloads"
    plain.mkdir()
    (plain / "My Old Book 001.jpg").write_bytes(b"x")
    assert pdfbook._pictures_title([plain / "My Old Book 001.jpg"]) == "My Old Book"


@pytest.mark.skipif(os.name != "nt", reason="Windows' own text recognition")
def test_page_pictures_become_an_ebook(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfbook, "WORK", tmp_path / "work")
    folder = tmp_path / "Mary and the Cows"
    files = _page_pictures(folder)
    res = pdfbook.convert(folder / "Page 9.png")           # one picture: every page in its folder
    assert res["read_pages"] == 3 and res["chapters"] == 2
    assert Path(res["out"]).parent == folder and res["title"] == "Mary and the Cows"
    import cleanread
    book = cleanread.Book(res["out"])
    text = " ".join(p.text for p in book.paras)
    # in page order, and the sideways page read the right way up
    assert text.index("Mary lived in a small white house") < text.index("She ran back up the hill") \
        < text.index("The meadow was wide and green")
    assert "MARY AND THE COWS" not in text
    kept = [json.loads(l) for l in next((tmp_path / "work").glob("*/pages.jsonl")).read_text().splitlines()]
    assert [k["file"] for k in kept] == ["Page 9.png", "Page 10.png", "Page 11.png"]
    assert kept[1]["turn"] in (90, 270) and kept[0]["turn"] == 0
    assert len(files) == 3


def test_no_pictures_says_so_plainly(tmp_path):
    with pytest.raises(pdfbook.ConvertError, match="No page pictures"):
        pdfbook.convert([tmp_path / "a.txt", tmp_path / "b.txt"])


def test_pictures_offer_make_an_ebook(app, tmp_path, monkeypatch):
    ui, a = app
    folder = tmp_path / "scans"
    folder.mkdir()
    for n in range(1, 4):
        (folder / f"scan{n}.jpg").write_bytes(b"x")
    a.book_path = str(folder / "scan1.jpg")
    a._refresh()
    assert "Pictures of a book's pages (3 in this folder)" in " ".join(_texts(a.pdf_box))
    assert a._book_name() == "scans"
    called = []
    monkeypatch.setattr(pdfbook, "convert", lambda src, **k: called.append(src) or
                        {"out": str(folder / "scans.epub"), "title": "Scans"})
    sent = []
    assert a._as_ebook(a.job, a.book_path, sent.append) == str(folder / "scans.epub")
    assert called == [a.book_path] and sent[-1][0] == "converted"
