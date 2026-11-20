"""Converting an audiobook you already have (the owner, 2026-11-20: "also add in the I can load
either mp3 or m4b and convert"): an M4B becomes one MP3, an MP3 (or a book's MP3 chapter files)
becomes one M4B, keeping the chapters, title, author and cover; the new file goes next to the old,
which isn't changed."""
import subprocess
import time

import pytest

from test_readaloud import R, _probe, needs_ffmpeg
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


def _tone(path, secs, title=None, album="Nearly Safe", artist="Jane Author", extra=()):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
    cmd += list(extra)
    for k, v in (("title", title), ("album", album), ("artist", artist)):
        if v:
            cmd += ["-metadata", f"{k}={v}"]
    subprocess.run(cmd + [str(path)], check=True)


def _cover(path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1",
                    str(path)], check=True)


def _m4b(tmp_path):
    """A small M4B as other programs make them: two chapters, tags and a cover."""
    meta = tmp_path / "meta.txt"
    meta.write_text(";FFMETADATA1\ntitle=Nearly Safe\nalbum=Nearly Safe\nartist=Jane Author\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=3000\ntitle=Chapter One\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=3000\nEND=6000\ntitle=Chapter Two\n", encoding="utf8")
    cover = tmp_path / "c.jpg"
    _cover(cover)
    out = tmp_path / "Nearly Safe.m4b"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-i", str(meta), "-i", str(cover), "-map", "0:a", "-map", "2:v", "-c:v", "copy",
                    "-disposition:v:0", "attached_pic", "-map_metadata", "1", "-map_chapters", "1",
                    "-c:a", "aac", "-b:a", "64k", "-f", "ipod", str(out)], check=True)
    return out


def test_what_converting_makes(tmp_path):
    files, kind, out = R.convert_plan([tmp_path / "Book.m4b"])
    assert kind == "mp3" and out == tmp_path / "Book.mp3"
    files, kind, out = R.convert_plan([tmp_path / "Book.mp3"])
    assert kind == "m4b" and out == tmp_path / "Book.m4b"
    files, kind, out = R.convert_plan([tmp_path / "10 - End.mp3", tmp_path / "2 - Middle.mp3",
                                       tmp_path / "1 - Start.mp3"])
    assert [f.name for f in files] == ["1 - Start.mp3", "2 - Middle.mp3", "10 - End.mp3"]     # in order
    assert kind == "m4b" and out.parent == tmp_path and out.suffix == ".m4b"
    with pytest.raises(R.BookError, match="isn't an MP3 or M4B"):
        R.convert_plan([tmp_path / "Book.epub"])
    assert R._chapter_name("03 - The Storm") == "The Storm" and R._chapter_name("Track 03") == "Track 03"


@needs_ffmpeg
def test_an_m4b_becomes_one_mp3_keeping_everything(tmp_path):
    src = _m4b(tmp_path)
    before = src.read_bytes()
    said = []
    files, kind, out = R.convert_plan([src])
    res = R.convert_audiobook(files, out, progress=lambda f, m: said.append(m))
    assert res["file"] == str(tmp_path / "Nearly Safe.mp3") and res["chapters"] == 2
    fmt = _probe(out, "-show_format")["format"]
    assert fmt["format_name"] == "mp3" and abs(float(fmt["duration"]) - 6) < 0.3
    assert fmt["tags"]["title"] == "Nearly Safe" and fmt["tags"]["artist"] == "Jane Author"
    assert [c["tags"]["title"] for c in _probe(out, "-show_chapters")["chapters"]] == ["Chapter One", "Chapter Two"]
    assert any(s.get("disposition", {}).get("attached_pic") for s in _probe(out, "-show_streams")["streams"])
    assert any(m.startswith("Making the MP3 file") for m in said)
    assert src.read_bytes() == before                                         # the original as it was
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix in (".mp3", ".m4b")) == \
        ["Nearly Safe.m4b", "Nearly Safe.mp3"]


@needs_ffmpeg
def test_mp3_chapter_files_become_one_m4b(tmp_path):
    book = tmp_path / "Nearly Safe (MP3)"
    book.mkdir()
    for name, secs in (("01 - Arrival.mp3", 2), ("02 - The Storm.mp3", 3), ("10 - Home Again.mp3", 2)):
        _tone(book / name, secs)
    _cover(book / "cover.jpg")
    files, kind, out = R.convert_plan(list(book.glob("*.mp3")))
    assert out == book / "Nearly Safe.m4b"                                   # named after the album
    res = R.convert_audiobook(files, out)
    assert res["chapters"] == 3
    fmt = _probe(out, "-show_format")["format"]
    assert abs(float(fmt["duration"]) - 7) < 0.4
    assert fmt["tags"]["title"] == "Nearly Safe" and fmt["tags"]["artist"] == "Jane Author"
    chapters = _probe(out, "-show_chapters")["chapters"]
    assert [c["tags"]["title"] for c in chapters] == ["Arrival", "The Storm", "Home Again"]
    assert abs(float(chapters[1]["start_time"]) - 2) < 0.2
    streams = _probe(out, "-show_streams")["streams"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "audio"] == ["aac"]
    assert any(s.get("disposition", {}).get("attached_pic") for s in streams)   # the folder's cover


@needs_ffmpeg
def test_a_cancelled_convert_leaves_nothing_half_made(tmp_path):
    src = tmp_path / "Long.mp3"
    _tone(src, 600)
    files, kind, out = R.convert_plan([src])
    with pytest.raises(R.Stopped):
        R.convert_audiobook(files, out, cancel=lambda: True)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Long.mp3"]


def test_a_file_that_isnt_sound_says_so(tmp_path):
    bad = tmp_path / "Broken.m4b"
    bad.write_bytes(b"not sound at all")
    with pytest.raises(R.BookError, match="couldn't be read as sound"):
        R.convert_audiobook([bad], tmp_path / "Broken.mp3")


@needs_ffmpeg
def test_convert_from_readaloud(window, tmp_path, monkeypatch):
    win, app = window
    src = _m4b(tmp_path)
    monkeypatch.setattr(win.filedialog, "askopenfilenames", lambda **k: (str(src),))
    asked = []
    monkeypatch.setattr(win.messagebox, "askyesno", lambda t, q, **k: asked.append(q) or True)
    monkeypatch.setattr(win, "chime", lambda: None)
    app.pick_convert()
    assert "Make an MP3 from “Nearly Safe.m4b”" in asked[0] and "“Nearly Safe.mp3”" in asked[0]
    end = time.time() + 30
    while time.time() < end and not (tmp_path / "Nearly Safe.mp3").exists():
        _pump(app, 0.1)
    _pump(app, 0.5)
    texts = [w.cget("text") for w in app.page.winfo_children() if w.winfo_class() == "Label"]
    assert "Your audiobook is ready" in texts
