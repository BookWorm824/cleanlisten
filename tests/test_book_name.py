"""A book's name comes from its file, not the folder it sits in (Jason, 2026-11-06: a book
sitting straight in Downloads was called "Downloads"). The folder's name only for a folder of
chapter files, or the folder above Disc 1, Disc 2..."""
import importlib.machinery
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _app():
    loader = importlib.machinery.SourceFileLoader("cl_gui_names", str(REPO / "CleanListen.pyw"))
    spec = importlib.util.spec_from_loader("cl_gui_names", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


APP = _app()
DL = Path(r"C:\Users\Lauren\Downloads")


def test_one_file_is_called_by_its_own_name():
    assert APP.book_title([DL / "My Book.m4b"]) == "My Book"
    assert APP.book_title([DL / "Wings of a Dream.mp3"]) == "Wings of a Dream"
    # even in a folder of its own, one file is named by itself
    assert APP.book_title([DL / "Nearly Free" / "Molly Black - Nearly Free.m4b"]) == \
        "Molly Black - Nearly Free"


def test_a_folder_of_chapter_files_is_called_by_the_folder():
    book = DL / "#3 Nearly Free"
    assert APP.book_title([book / "01.mp3", book / "02.mp3"]) == "#3 Nearly Free"


def test_discs_are_called_by_the_folder_above_them():
    book = DL / "Vermilion"
    assert APP.book_title([book / "Disc 1" / "01.mp3", book / "Disc 2" / "01.mp3"]) == "Vermilion"


def test_chapter_files_loose_in_downloads():
    files = [DL / "My Book - Part 01.mp3", DL / "My Book - Part 02.mp3"]
    assert APP.book_title(files) == "My Book"
    # names that don't agree: the first file's own name, never "Downloads"
    assert APP.book_title([DL / "a.mp3", DL / "b.mp3"]) == "a"
    assert APP.book_title([Path(r"C:\Users\Lauren\Desktop\x 1.mp3"),
                           Path(r"C:\Users\Lauren\Desktop\x 2.mp3")]) == "x"


def test_names_saved_by_older_versions_are_mended():
    assert APP.fix_title("Downloads", [DL / "My Book.m4b"]) == "My Book"
    # a name they gave it, or a right one, is kept
    assert APP.fix_title("My Own Name", [DL / "My Book.m4b"]) == "My Own Name"
    book = DL / "#3 Nearly Free"
    assert APP.fix_title("#3 Nearly Free", [book / "01.mp3", book / "02.mp3"]) == "#3 Nearly Free"
    # an old name from the book's own folder stays: only "Downloads", "Desktop"... are mended
    assert APP.fix_title("Nearly Free", [DL / "Nearly Free" / "Molly Black - Nearly Free.m4b"]) == \
        "Nearly Free"
    assert APP.fix_title("", [DL / "My Book.m4b"]) == ""
    assert APP.fix_title("Downloads", []) == "Downloads"


def test_the_queue_and_past_books_use_the_mended_name():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert 'j["title"] = fix_title(j.get("title"), j.get("audio"))' in src
    assert 'fix_title(info.get("title"), parts) or book_title(parts)' in src
