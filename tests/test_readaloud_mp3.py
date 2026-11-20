"""The audiobook as one MP3 instead of one M4B (the owner, 2026-11-20: "can you have the option to
save as mp3 or m4B"): a choice on the Save to step, kept for next time; the MP3 has the chapters,
title, author and cover inside, like the M4B."""
import subprocess
from pathlib import Path

from test_readaloud import R, STORY, _probe, make_epub, needs_ffmpeg
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


def test_the_file_ends_in_mp3_when_chosen(tmp_path):
    b = {"title": "Nearly Safe", "author": "Jane Author", "series": "Grace Ford", "number": "2"}
    assert R.out_path(b, tmp_path) == tmp_path / "Nearly Safe.m4b"
    assert R.out_path(b, tmp_path, kind="mp3") == tmp_path / "Nearly Safe.mp3"
    assert R.out_path(b, tmp_path, abs_layout=True, kind="mp3") == \
        tmp_path / "Jane Author" / "Grace Ford" / "Book 2 - Nearly Safe" / "Nearly Safe.mp3"


@needs_ffmpeg
def test_one_mp3_with_chapters_tags_and_cover(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    cover = tmp_path / "c.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1",
                    str(cover)], check=True)
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    b["cover"], b["cover_ext"] = cover.read_bytes(), ".png"
    out = R.out_path(b, tmp_path / "library", kind="mp3")
    jobdir = R.start_job(b, "bf_emma", 1.0, [1, 2], out)
    said = []
    for i in range(2):
        R.speak_chapter(jobdir, i, threads=1)
    res = R.assemble(jobdir, progress=lambda f, m: said.append((f, m)))
    assert Path(res["file"]) == out and out.exists() and not res["mp3_dir"]
    fmt = _probe(out, "-show_format")["format"]
    assert fmt["format_name"] == "mp3"
    assert fmt["tags"]["title"] == "Nearly Safe" and fmt["tags"]["artist"] == "Jane Author"
    chapters = _probe(out, "-show_chapters")["chapters"]
    assert [c["tags"]["title"] for c in chapters] == ["Chapter One", "Chapter Two"]
    streams = _probe(out, "-show_streams")["streams"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "audio"] == ["mp3"]
    assert any(s.get("disposition", {}).get("attached_pic") for s in streams)      # the cover
    whole = sum(R.probe_duration(R.chapter_file(jobdir, i)) for i in range(2))
    assert whole > 3 and abs(float(fmt["duration"]) - whole) < 0.5                  # nothing lost
    assert any(m.startswith("Making the MP3 file") for _, m in said)
    assert not list(out.parent.glob("~saving~*"))


def test_the_choice_is_on_the_save_step_and_kept(window, tmp_path, monkeypatch):
    win, app = window
    assert app.kind_var.get() in ("m4b", "mp3")
    app.kind_var.set("m4b")
    app._kind_changed()
    assert "M4B" in app.kind_note.cget("text") and app._step_summary(5).endswith("ebook")
    app.kind_var.set("mp3")
    app._kind_changed()
    assert "MP3" in app.kind_note.cget("text")
    assert app._step_summary(5).endswith(" · MP3")
    assert app.settings["kind"] == "mp3"
    app.book, app.book_path = {"title": "Nearly Safe", "author": "", "chapters": []}, str(tmp_path / "b.epub")
    app.folder = None
    out, _ = app._out_file()
    assert out == tmp_path / "Nearly Safe.mp3"
    app.kind_var.set("m4b")
    app._kind_changed()
    assert app._out_file()[0].suffix == ".m4b"
    _pump(app, 0.1)
