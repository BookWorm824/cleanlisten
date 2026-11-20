"""A scanned PDF (pictures of the pages, no text) opens in ReadAloud (the owner, 2026-11-19: "it
won't open a pdf", with "No text was found in this PDF"): its pages are read the way CleanRead does
(pdfbook, Windows' own text recognition) into an EPUB kept with ReadAloud's work, never next to the
PDF, and that is read aloud; the audiobook still goes next to the PDF."""
import os

import pytest

import pdfbook
import readaloud as R
from test_pdf_ebook import TEXT_PAGES, _pictures_only, _text_pdf
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


@pytest.mark.skipif(os.name != "nt", reason="Windows' own text recognition")
def test_a_scanned_pdf_is_read_aloud(tmp_path, monkeypatch):
    monkeypatch.setattr(pdfbook, "WORK", tmp_path / "work")
    typed, scanned = tmp_path / "typed.pdf", tmp_path / "Mary and the Cows.pdf"
    _text_pdf(typed, TEXT_PAGES)
    _pictures_only(typed, scanned)
    said = []
    book = R.load_book(scanned, progress=lambda f, m: said.append((f, m)))
    text = " ".join(t for c in book["chapters"] for _, t in c["paras"])
    assert "Mary lived in a small white house at the edge of the woods" in text
    assert "MARY AND THE COWS" not in text                     # the running head is dropped
    assert book["path"] == str(scanned)                         # the audiobook goes next to the PDF
    assert any("Reading the words on page" in m for _, m in said)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Mary and the Cows.pdf", "typed.pdf", "work"]
    # a PDF with text is read as before, without the text recognition
    said.clear()
    plain = R.load_book(typed, progress=lambda f, m: said.append((f, m)))
    assert "Mary lived in a small white house" in " ".join(t for c in plain["chapters"] for _, t in c["paras"])
    assert not said


def test_a_cancelled_reading_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pictures_only", lambda path: True)

    def stopped(path, out=None, progress=None, cancel=None, language="en"):
        assert cancel() is True
        raise pdfbook.Stopped()
    monkeypatch.setattr(pdfbook, "convert", stopped)
    monkeypatch.setattr(pdfbook, "_key", lambda path: "k")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(pdfbook.Stopped):
        R.load_book(pdf, cancel=lambda: True)


def test_a_failed_reading_says_so_plainly(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pictures_only", lambda path: True)

    def fails(*a, **k):
        raise pdfbook.ConvertError("Couldn't get the PDF page reader. Check the internet connection and try again.")
    monkeypatch.setattr(pdfbook, "convert", fails)
    monkeypatch.setattr(pdfbook, "_key", lambda path: "k")
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(R.BookError, match="internet connection"):
        R.load_book(pdf)


def test_the_page_says_what_its_doing_meanwhile(window, tmp_path, monkeypatch):
    import threading
    import time
    win, app = window
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4\n")
    started, ended = threading.Event(), threading.Event()

    def slow(path, progress=None, cancel=None, language="en"):
        progress(0.25, "Reading the words on page 3 of 12")
        started.set()
        while not cancel():
            time.sleep(0.02)
        ended.set()
        raise pdfbook.Stopped()
    monkeypatch.setattr(win.engine, "load_book", slow)
    monkeypatch.setattr(win.filedialog, "askopenfilename", lambda **k: str(f))
    app.pick_book()
    assert started.wait(5)
    _pump(app, 0.3)
    assert app.book_lbl.cget("text") == "Reading the words on page 3 of 12  (25%)"
    app._opening = object()                 # another book chosen: the reading stops quietly
    assert ended.wait(5)
    _pump(app, 0.3)
    assert app.q.empty()                    # no error box


class _GoogleDocsPage:
    """A page as pypdf reads a PDF from Google Docs: one word to a line, unless asked to keep the
    layout (the owner's "Always Here Script", 2026-11-19)."""
    LINES = ["ALWAYS HERE", "SCENE 1 � THE PLAYROOM", "NARRATOR:",
             "One sunny afternoon, a little boy named Landon sat on the floor of the playroom. The warm",
             "afternoon sun shone through the windows while toys, blocks, and stuffed animals surrounded",
             "him.", "LANDON:", "�And he's coming around the corner! Faster! Faster!�"]

    def extract_text(self, extraction_mode="plain"):
        if extraction_mode == "layout":
            return "\n\n".join("   " + l for l in self.LINES)
        return "\n \n".join(w for l in self.LINES for w in l.split())


def test_a_pdf_from_google_docs_is_read_as_words_not_letters():
    # it came out one word to a line, was taken for a scan, and the page reader's text was letters
    # spaced apart ("O n e s u n n y aftfte rn o o n"), which the voice spelled out
    lines = R._pdf_lines(_GoogleDocsPage())
    assert lines[3].startswith("One sunny afternoon, a little boy named Landon")
    assert lines[1] == "SCENE 1 — THE PLAYROOM"                     # the dash the font didn't name
    assert lines[-1] == '"And he\'s coming around the corner! Faster! Faster!"'


def test_a_scripts_speaker_labels_stand_on_their_own(monkeypatch):
    import pypdf

    class Reader:
        def __init__(self, path):
            self.pages = [_GoogleDocsPage()]
            self.metadata = {"/Title": "Always Here Script"}
            self.is_encrypted = False
    monkeypatch.setattr(pypdf, "PdfReader", Reader)
    title, author, cover, chapters = R.read_pdf("Always Here Script.pdf")
    paras = [t for c in chapters for _, t in c["paras"]]
    assert "NARRATOR:" in paras and "LANDON:" in paras                  # not stuck to the line before
    assert any(p.startswith("One sunny afternoon") and p.endswith("surrounded him.") for p in paras)


def test_a_pdf_with_text_never_goes_to_the_page_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_pictures_only", lambda path: False)
    monkeypatch.setattr(pdfbook, "convert", lambda *a, **k: pytest.fail("sent to the page reader"))
    monkeypatch.setattr(R, "read_pdf", lambda path: (_ for _ in ()).throw(R.BookError(R.SCANNED + " (x)")))
    pdf = tmp_path / "odd.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(R.BookError, match="No text was found"):
        R.load_book(pdf)
