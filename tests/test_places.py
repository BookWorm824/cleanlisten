"""Choosing where the chapter files and the M4B go, and an Audiobookshelf library's folders
(Lauren, 2026-11-04: "allow me to choose where to save the files ... it needs to set the folder
up for audiobookshelf")."""
from pathlib import Path

import pytest

import cleanlisten as E
from test_m4b import chapters, has_cover, job, mp3_book, picture, probe  # noqa: F401
from test_smoke import _ffmpeg


def test_series_from_the_folders():
    book = Path("F:/Audio/Grace Ford Series/#2 Nearly Safe")
    assert E.guess_series([book / "Nearly Safe 01.mp3"]) == ("Grace Ford", "2")
    assert E.guess_series([book / "Disc 1" / "01.mp3", book / "Disc 2" / "01.mp3"]) == \
        ("Grace Ford", "2")
    assert E.guess_series([Path("F:/Audio/Mitford/Book 03 - Out to Canaan/a.mp3")]) == \
        ("Mitford", "3")
    assert E.guess_series([Path("F:/Audio/Mitford/1. At Home in Mitford/a.mp3")]) == ("Mitford", "1")
    for plain in ("F:/Audio/Nearly Safe/a.mp3", "F:/Audio/1984/a.mp3",
                  "F:/Audio/2001 A Space Odyssey/a.mp3", "F:/#2 Nearly Safe/a.mp3"):
        assert E.guess_series([Path(plain)]) == ("", ""), plain


def test_audiobookshelf_folders():
    lib = Path("G:/Audiobookshelf")
    # Audiobookshelf's scanner: Author / Series / "Book 2 - Title" (the number from "Book 2 - ")
    assert E.abs_folder(lib, "#2 Nearly Safe", "Lisa Harris", "Grace Ford", "2") == \
        lib / "Lisa Harris" / "Grace Ford" / "Book 2 - Nearly Safe"
    assert E.abs_folder(lib, "Nearly Safe", "Lisa Harris", "Grace Ford", "02") == \
        lib / "Lisa Harris" / "Grace Ford" / "Book 2 - Nearly Safe"
    assert E.abs_folder(lib, "Nearly Safe", "Lisa Harris") == lib / "Lisa Harris" / "Nearly Safe"
    assert E.abs_folder(lib, "Nearly Safe", "", "Grace Ford", "2.5") == \
        lib / "Unknown Author" / "Grace Ford" / "Book 2.5 - Nearly Safe"
    assert E.abs_folder(lib, "Nearly Safe", "", "Grace Ford") == \
        lib / "Unknown Author" / "Grace Ford" / "Nearly Safe"
    assert E.abs_folder(lib, "Nearly Safe") == lib / "Nearly Safe"
    assert E.abs_folder(lib, 'What: "Now"?', "A/B") == lib / "AB" / "What Now"
    assert E.abs_folder(lib, "Nearly Safe", "X", "Grace Ford", "two") == \
        lib / "X" / "Grace Ford" / "Nearly Safe"          # not a number: no number


def test_file_names_windows_takes():
    assert E.safe_name('A: "B"? <C> | D...') == "A B C D"
    assert E.safe_name("  ") == "Audiobook"
    assert E.strip_number("#2 Nearly Safe", "2") == "Nearly Safe"
    assert E.strip_number("#2 Nearly Safe", "3") == "#2 Nearly Safe"
    assert E.strip_number("Catch-22", "22") == "Catch-22"


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


@needs_ffmpeg
def test_m4b_into_an_audiobookshelf_library(tmp_path, mp3_book):
    parts, words = mp3_book
    work = job(tmp_path, parts, words)
    out, lib, yoto = tmp_path / "Clean", tmp_path / "Library", tmp_path / "Yoto"
    other = yoto / "Another Book"
    other.mkdir(parents=True)
    (other / "01 Keep me.mp3").write_bytes(b"x")
    (yoto / "loose.mp3").write_bytes(b"x")
    res = E.render(work, out, chapters=True, m4b=True, log=lambda m: None, chapters_dir=yoto,
                   m4b_dir=lib, abs_layout=True, series="Clinic Files", series_no="2")
    book = lib / "Cate Quinn" / "Clinic Files" / "Book 2 - The Clinic" / "The Clinic.m4b"
    assert res["m4b"]["file"] == str(book) and book.exists() and has_cover(book)
    assert [t for _, t in chapters(book)] == ["Chapter 1", "Chapter 2"]
    assert probe(book)["format"]["tags"]["title"] == "The Clinic"
    # the chapter files in their own folder in the one chosen; nothing else there touched
    assert sorted(p.name for p in (yoto / "The Clinic").glob("*.mp3")) == \
        ["01 Chapter 1.mp3", "02 Chapter 2.mp3"]
    assert (other / "01 Keep me.mp3").exists() and (yoto / "loose.mp3").exists()
    assert res["chapters"]["folders"] == [str(yoto / "The Clinic")]
    # the clean copy and report still in the usual place, and nothing left in it
    assert (out / "CleanListen report.txt").exists() and not (out / "Chapters").exists()
    assert not list(out.glob("*.m4b")) and not list(lib.rglob("~saving~*"))
    report = (out / "CleanListen report.txt").read_text(encoding="utf8")
    assert str(book.parent) in report and str(yoto / "The Clinic") in report


@needs_ffmpeg
def test_m4b_into_a_plain_folder(tmp_path, mp3_book):
    parts, words = mp3_book
    work = job(tmp_path, parts, words)
    res = E.render(work, tmp_path / "Clean", m4b=True, log=lambda m: None,
                   m4b_dir=tmp_path / "Phone", abs_layout=False)
    assert res["m4b"]["file"] == str(tmp_path / "Phone" / "The Clinic.m4b")


@needs_ffmpeg
def test_an_m4b_book_is_copied_into_the_library(tmp_path):
    from test_m4b import ff
    src = tmp_path / "Grace Ford Series" / "#2 Nearly Safe" / "Nearly Safe.m4b"
    src.parent.mkdir(parents=True)
    pic = picture(tmp_path / "pic.jpg")
    ff("-f", "lavfi", "-i", "sine=f=440:d=10", "-i", pic, "-map", "0:a", "-map", "1:v",
       "-c:a", "aac", "-b:a", "64k", "-c:v", "copy", "-disposition:v", "attached_pic",
       "-metadata", "title=#2 Nearly Safe", "-metadata", "artist=Lisa Harris", src)
    work = job(tmp_path, [src])
    series, no = E.guess_series([src])
    res = E.render(work, tmp_path / "Clean", m4b=True, log=lambda m: None,
                   m4b_dir=tmp_path / "Lib", abs_layout=True, series=series, series_no=no)
    book = tmp_path / "Lib" / "Lisa Harris" / "Grace Ford" / "Book 2 - Nearly Safe" / "Nearly Safe.m4b"
    assert res["m4b"]["file"] == str(book) and book.exists()
    assert (tmp_path / "Clean" / "Nearly Safe.m4b").exists()       # the clean copy stays
    assert probe(book)["format"]["tags"]["title"] == "Nearly Safe"
