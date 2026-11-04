"""One M4B with cover and chapters next to the Yoto chapter files (2026-11-04: the owner made
these by hand in AudiobookConverter from CleanListen's chapter files), and an M4B's chapter
marks moving with the cuts. Needs ffmpeg (skipped without it, like test_smoke)."""
import json
import subprocess

import pytest

import cleanlisten as E
from test_smoke import _ffmpeg

pytestmark = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True)


def probe(path):
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
         "-show_chapters", str(path)], capture_output=True, text=True, check=True).stdout)


def picture(path, color="red"):
    ff("-f", "lavfi", "-i", f"color=c={color}:s=200x200", "-frames:v", "1", path)
    return path


def job(tmp_path, parts, words=None):
    work = tmp_path / "job"
    work.mkdir()
    keys = [str(p.resolve()) for p in parts]
    (work / "analysis.json").write_text(json.dumps({"parts": keys, "mutes": [], "scenes": []}))
    (work / "transcript.json").write_text(json.dumps(
        {k: (words or {}).get(i, []) for i, k in enumerate(keys)}))
    return work


def said(*pairs):
    """Words for a transcript: (start, "Chapter one") -> 0.3 s a word."""
    out = []
    for t, text in pairs:
        for w in text.split():
            out.append({"t": w, "s": round(t, 3), "e": round(t + 0.25, 3)})
            t += 0.3
    return out


def chapters(path):
    return [(round(float(c["start_time"])), c["tags"]["title"]) for c in probe(path)["chapters"]]


def has_cover(path):
    return any(s.get("disposition", {}).get("attached_pic") for s in probe(path)["streams"])


@pytest.fixture
def m4b_book(tmp_path):
    """A 2-minute M4B with a cover and two chapters (one at 0:00, one at 1:00)."""
    book = tmp_path / "Book"
    book.mkdir()
    meta = tmp_path / "meta.txt"
    meta.write_text(";FFMETADATA1\ntitle=Test Book\nartist=Jane Author\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=60000\ntitle=Chapter One\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=60000\nEND=120000\ntitle=Chapter Two\n")
    pic = picture(tmp_path / "pic.jpg")
    src = book / "Test Book.m4b"
    ff("-f", "lavfi", "-i", "sine=f=440:d=120", "-i", pic, "-i", meta, "-map", "0:a", "-map", "1:v",
       "-c:a", "aac", "-b:a", "64k", "-c:v", "copy", "-disposition:v", "attached_pic",
       "-map_metadata", "2", "-map_chapters", "2", src)
    return src


def test_m4b_chapter_marks_move_with_the_cuts(tmp_path, m4b_book):
    # before 1.13.7, cutting 0:10-0:40 left "Chapter Two" at 1:00 in a 1:30 book
    work = job(tmp_path, [m4b_book])
    E.render(work, tmp_path / "Clean", cuts=[{"part": 0, "s": 10.0, "e": 40.0}], log=lambda m: None)
    clean = tmp_path / "Clean" / "Test Book.m4b"
    assert chapters(clean) == [(0, "Chapter One"), (30, "Chapter Two")]
    assert has_cover(clean)
    assert E.probe_duration(clean) == pytest.approx(90, abs=0.5)


def test_an_m4b_book_stays_one_m4b_with_its_own_chapters(tmp_path, m4b_book):
    work = job(tmp_path, [m4b_book])
    res = E.render(work, tmp_path / "Clean", cuts=[{"part": 0, "s": 70.0, "e": 80.0}],
                   chapters=True, m4b=True, log=lambda m: None)
    clean = tmp_path / "Clean" / "Test Book.m4b"
    assert res["m4b"]["file"] == str(clean) and res["m4b"]["cover"]
    assert chapters(clean) == [(0, "Chapter One"), (60, "Chapter Two")]
    # the Yoto files follow the book's own chapters too (not "Section 1")
    assert res["chapters"]["titles"] == ["Chapter One", "Chapter Two"]
    assert [p.name for p in sorted((tmp_path / "Clean" / "Chapters").glob("*.mp3"))] == \
        ["01 Chapter One.mp3", "02 Chapter Two.mp3"]
    assert probe(clean)["format"]["tags"]["artist"] == "Jane Author"


@pytest.fixture
def mp3_book(tmp_path):
    """Two 12-second MP3 parts at 64k, tagged with the author, and a cover.jpg beside them."""
    book = tmp_path / "The Clinic"
    book.mkdir()
    parts = []
    for i, f in enumerate((440, 550), 1):
        p = book / f"The Clinic - Part {i:02d}.mp3"
        ff("-f", "lavfi", "-i", f"sine=f={f}:d=12", "-c:a", "libmp3lame", "-b:a", "64k",
           "-metadata", "artist=Cate Quinn", "-metadata", "album=The Clinic",
           "-metadata", f"title=Part {i:02d}", p)
        parts.append(p)
    picture(book / "big picture.png", "blue")
    picture(book / "cover.jpg")
    words = {0: said((0.5, "Chapter one"), (2.0, "It was a quiet morning.")),
             1: said((0.5, "Chapter two"), (2.0, "Then everyone went home."))}
    return parts, words


def test_one_m4b_from_mp3_parts_matches_the_yoto_files(tmp_path, mp3_book):
    parts, words = mp3_book
    work = job(tmp_path, parts, words)
    out = tmp_path / "The Clinic" / "Clean"
    res = E.render(work, out, cuts=[{"part": 0, "s": 4.0, "e": 6.0}], chapters=True, m4b=True,
                   log=lambda m: None)
    book = out / "The Clinic.m4b"
    assert res["m4b"]["file"] == str(book)
    yoto = sorted((out / "Chapters").glob("*.mp3"))
    assert [p.name for p in yoto] == ["01 Chapter 1.mp3", "02 Chapter 2.mp3"]
    # one chapter per Yoto file, with its name, starting where the file before it ends
    assert chapters(book) == [(0, "Chapter 1"), (round(E.probe_duration(yoto[0])), "Chapter 2")]
    assert E.probe_duration(book) == pytest.approx(22, abs=0.5)
    assert has_cover(book)
    tags = probe(book)["format"]["tags"]
    assert tags["artist"] == "Cate Quinn" and tags["title"] == "The Clinic"
    a = next(s for s in probe(book)["streams"] if s["codec_type"] == "audio")
    assert a["codec_name"] == "aac" and int(a["bit_rate"]) < 90000       # 64k, not 128k
    assert not list(out.glob("~saving~*")) and not (work / "m4b_pieces").exists()


def test_m4b_alone_leaves_no_chapter_folder(tmp_path, mp3_book):
    parts, words = mp3_book
    work = job(tmp_path, parts, words)
    out = tmp_path / "Clean"
    pic = picture(tmp_path / "chosen.png", "green")
    res = E.render(work, out, m4b=True, cover=str(pic), author="Someone Else", log=lambda m: None)
    assert res["chapters"] is None and not (out / "Chapters").exists()
    book = out / "The Clinic.m4b"
    assert [t for _, t in chapters(book)] == ["Chapter 1", "Chapter 2"]
    assert probe(book)["format"]["tags"]["artist"] == "Someone Else" and has_cover(book)
    assert not list(work.glob("m4b_*"))


def test_the_cover_is_found(tmp_path, mp3_book, m4b_book):
    parts, _ = mp3_book
    assert E.find_cover(parts) == ("file", str(parts[0].parent / "cover.jpg"))    # cover.jpg wins
    assert E.find_cover([m4b_book]) == ("book", str(m4b_book))              # inside the book
    pic = E.cover_file(E.find_cover([m4b_book]), tmp_path)
    assert pic and pic.endswith("cover.jpg")
    (parts[0].parent / "cover.jpg").unlink()
    assert E.find_cover(parts)[1].endswith("big picture.png")
    assert E.cover_file(str(tmp_path / "missing.jpg"), tmp_path) is None


def test_chapter_list_file(tmp_path):
    f = tmp_path / "meta.txt"
    n = E.write_ffmeta(f, {"title": "A = B; #1", "artist": ""},
                       [(0, "Prologue"), (60, "Chapter 1"), (60.2, "Gone"), (90, "")], 120)
    text = f.read_text(encoding="utf8")
    assert n == 3 and "title=A \\= B\\; \\#1" in text and "artist" not in text
    assert "START=60000\nEND=90000\ntitle=Chapter 1" in text and "title=Chapter 3" in text
