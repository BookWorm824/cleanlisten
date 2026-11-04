"""ReadAloud (ebook -> audiobook): getting text ready to read, reading books, and making the
M4B. The voice itself is a stand-in tone (READALOUD_FAKE_VOICE), so no 334 MB download."""
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from conftest import REAL_APPDATA, REPO

os.environ["READALOUD_FAKE_VOICE"] = "1"
import readaloud as R  # noqa: E402


def _ffmpeg():
    if not shutil.which("ffmpeg"):
        app_bin = Path(REAL_APPDATA) / "CleanListen" / "app" / "bin"
        if (app_bin / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(app_bin) + os.pathsep + os.environ["PATH"]
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


# ---------- text ----------
@pytest.mark.parametrize("raw, want", [
    ("CHAPTER IV. MARTHA", "Chapter 4. Martha"),
    ("Chapter XII", "Chapter 12"),
    ("He said—no, he shouted—“Go!”", 'He said, no, he shouted, "Go!"'),
    ("It was over…", "It was over..."),
    ("See www.example.com for more[3].", "See for more."),
    ("The NASA team and the FBI came. WHAT a day!", "The NASA team and the FBI came. What a day!"),
    ("“I won’t,” she said.", '"I won\'t," she said.'),
])
def test_text_is_made_ready_to_read(raw, want):
    assert R.speakable(raw) == want


def test_titles_in_capitals_read_nicely():
    assert R.title_case("CHAPTER XX. “I SHALL LIVE FOREVER”") == 'Chapter XX. “I Shall Live Forever”'
    assert R.title_case("THE KEY TO THE GARDEN") == "The Key to the Garden"


def test_sentences_dont_split_after_mr_or_an_initial():
    s = R.sentences("Mr. Craven went to J. R. Smith's house. It was late! Was it? Yes.")
    assert s == ["Mr. Craven went to J. R. Smith's house.", "It was late!", "Was it?", "Yes."]


def test_a_very_long_sentence_is_split_at_its_commas():
    long = ", ".join(["and the wind blew over the moor and the heather"] * 12) + "."
    parts = R.chunks(long)
    assert len(parts) > 1 and all(len(p) <= R.MAX_CHUNK for p in parts)
    assert " ".join(parts).split() == long.split()


# ---------- books ----------
def make_epub(path, chapters, series=True, cover=True):
    """A small EPUB 3: a contents page, then chapters [(title, [paragraphs])]."""
    z = zipfile.ZipFile(path, "w")
    z.writestr("mimetype", "application/epub+zip")
    z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container><rootfiles>'
               '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
    docs = [("toc.xhtml", "Contents", ["Chapter One", "Chapter Two"])] + \
        [(f"c{i}.xhtml", t, ps) for i, (t, ps) in enumerate(chapters)]
    items, spine, nav = [], [], []
    for name, title, paras in docs:
        body = f"<h1>{title}</h1>" + "".join(f"<p>{p}</p>" for p in paras)
        z.writestr(f"OEBPS/{name}", f'<?xml version="1.0" encoding="utf-8"?><html><body>{body}</body></html>')
        items.append(f'<item id="{name}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{name}"/>')
        nav.append(f'<li><a href="{name}">{title}</a></li>')
    z.writestr("OEBPS/nav.xhtml", f'<html><body><nav epub:type="toc"><ol>{"".join(nav)}</ol></nav></body></html>')
    items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    if cover:
        z.writestr("OEBPS/images/cover.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50)
        items.append('<item id="cov" href="images/cover.png" media-type="image/png" properties="cover-image"/>')
    meta = ('<meta name="calibre:series" content="Grace Ford"/><meta name="calibre:series_index" content="2.0"/>'
            if series else "")
    z.writestr("OEBPS/content.opf", f'<?xml version="1.0"?><package><metadata>'
               f'<dc:title>Nearly Safe</dc:title><dc:creator>Jane Author</dc:creator>{meta}</metadata>'
               f'<manifest>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>')
    z.close()
    return path


STORY = [("Chapter One", ["It was a dark night. Mrs. Smith locked the door.", "* * *",
                          "Morning came at last, bright and cold."]),
         ("Chapter Two", ["She opened the letter and read it twice."])]


def test_an_epub_is_read_with_its_chapters_series_and_cover(tmp_path):
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    assert (b["title"], b["author"], b["series"], b["number"]) == ("Nearly Safe", "Jane Author", "Grace Ford", "2")
    assert b["cover"].startswith(b"\x89PNG") and b["cover_ext"] == ".png"
    titles = [c["title"] for c in b["chapters"]]
    assert titles == ["Contents", "Chapter One", "Chapter Two"]
    assert [c["read"] for c in b["chapters"]] == [False, True, True]      # contents left out
    one = b["chapters"][1]["paras"]
    assert ["b", ""] in one                                              # the scene break is a pause
    assert one[0] == ["h", "Chapter One"]


def test_a_whole_story_under_a_contents_like_title_is_still_read(tmp_path):
    # Project Gutenberg's Velveteen Rabbit kept the story under "List of Illustrations"
    story = [("List of Illustrations", ["There was once a velveteen rabbit. " * 10] * 160)]
    b = R.load_book(make_epub(tmp_path / "rabbit.epub", story, series=False, cover=False))
    assert b["chapters"][-1]["read"] is True
    assert b["series"] == "" and b["cover"] is None


def test_a_word_file_is_read_with_its_headings_as_chapters(tmp_path):
    p = tmp_path / "story.docx"
    para = '<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
    body = (para.format(s="Heading1", t="Chapter 1") + para.format(s="Normal", t="Once upon a time.")
            + para.format(s="Heading1", t="Chapter 2") + para.format(s="Normal", t="The end &amp; all."))
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f'<w:document><w:body>{body}</w:body></w:document>')
        z.writestr("docProps/core.xml", "<cp:coreProperties><dc:title>My Story</dc:title>"
                   "<dc:creator>Lauren</dc:creator></cp:coreProperties>")
    b = R.load_book(p)
    assert (b["title"], b["author"]) == ("My Story", "Lauren")
    assert [c["title"] for c in b["chapters"]] == ["Chapter 1", "Chapter 2"]
    assert b["chapters"][1]["paras"][-1] == ["p", "The end & all."]


def test_a_kindle_book_says_what_to_do(tmp_path):
    p = tmp_path / "book.azw3"
    p.write_bytes(b"x")
    with pytest.raises(R.BookError, match="Calibre"):
        R.load_book(p)


def test_sample_text_comes_from_the_story(tmp_path):
    story = [("Chapter One", ["The rain fell all day on the little house by the river. " * 4])]
    b = R.load_book(make_epub(tmp_path / "b.epub", story))
    assert R.sample_text(b).startswith("The rain fell all day")


# ---------- making the audiobook ----------
def _probe(path, what):
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", what, str(path)],
                                     capture_output=True, text=True).stdout)


@needs_ffmpeg
def test_the_audiobook_is_made_with_chapters_tags_and_mp3s(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    cover = tmp_path / "c.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1",
                    str(cover)], check=True)
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    b["cover"], b["cover_ext"] = cover.read_bytes(), ".png"
    out = R.out_path(b, tmp_path / "library", abs_layout=True)
    assert out == tmp_path / "library" / "Jane Author" / "Grace Ford" / "Book 2 - Nearly Safe" / "Nearly Safe.m4b"
    jobdir = R.start_job(b, "bf_emma", 1.0, [1, 2], out, {"mp3": True})
    res = R.Maker(jobdir, workers=(2, 1)).run()
    assert Path(res["file"]) == out and out.exists()
    chapters = _probe(out, "-show_chapters")["chapters"]
    assert [c["tags"]["title"] for c in chapters] == ["Chapter One", "Chapter Two"]
    fmt = _probe(out, "-show_format")["format"]
    assert fmt["tags"]["title"] == "Nearly Safe" and fmt["tags"]["artist"] == "Jane Author"
    streams = _probe(out, "-show_streams")["streams"]
    assert any(s.get("disposition", {}).get("attached_pic") for s in streams)      # the cover
    assert sorted(p.name for p in Path(res["mp3_dir"]).glob("*.mp3")) == ["01 - Chapter One.mp3",
                                                                         "02 - Chapter Two.mp3"]
    assert (jobdir / "done.json").exists() and R.unfinished_jobs() == []


@needs_ffmpeg
def test_a_stopped_book_carries_on_where_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    jobdir = R.start_job(b, "af_heart", 1.0, [1, 2], tmp_path / "out.m4b")
    R.speak_chapter(jobdir, 0, threads=1)                     # one chapter read, then it stopped
    (left,) = R.unfinished_jobs()
    assert left[0] == jobdir and (left[2], left[3]) == (1, 2)
    first = R.chapter_file(jobdir, 0).stat().st_mtime_ns
    R.Maker(jobdir, workers=(1, 1)).run()
    assert R.chapter_file(jobdir, 0).stat().st_mtime_ns == first     # not read again
    assert len(_probe(tmp_path / "out.m4b", "-show_chapters")["chapters"]) == 2


@needs_ffmpeg
def test_stop_keeps_what_was_read(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    jobdir = R.start_job(b, "af_heart", 1.0, [1, 2], tmp_path / "out.m4b")
    (jobdir / "stop").write_text("stop")
    with pytest.raises(R.Stopped):
        R.speak_chapter(jobdir, 0, threads=1)
    assert not R.chapter_file(jobdir, 0).exists() and not list(jobdir.glob("~*"))
    # starting again clears the stop
    jobdir = R.start_job(b, "af_heart", 1.0, [1, 2], tmp_path / "out.m4b")
    assert not (jobdir / "stop").exists()


def test_time_left_reads_plainly():
    assert R.fmt_left(30) == "about a minute left"
    assert R.fmt_left(25 * 60) == "about 26 minutes left"
    assert R.fmt_left(2 * 3600 + 14 * 60) == "about 2 hours 15 minutes left"


def test_workers_fit_the_pc():
    n, threads = R.workers_for_pc()
    assert 1 <= n <= 4 and 2 <= threads <= 8


# ---------- shipping ----------
def test_readaloud_ships_and_opens_from_the_launcher():
    files = json.loads((REPO / "version.json").read_text())["files"]
    for f in ("readaloud.py", "ReadAloud.pyw", "readaloud.ico", "cleanread.py", "cleanlisten.py", "freezes.py"):
        assert f in files
    launcher = (REPO / "launcher.pyw").read_text("utf8")
    assert '"aloud": ("ReadAloud", "ReadAloud.pyw")' in launcher
    assert '"aloud": ("ReadAloud", "readaloud.ico")' in launcher
    assert "ensure_readaloud_shortcut" in (REPO / "CleanListen.pyw").read_text("utf8")
    assert "shortcuts.ensure_readaloud_shortcut()" in (REPO / "ReadAloud.pyw").read_text("utf8")


def _real_model():
    for d in (os.environ.get("READALOUD_REAL_MODEL"),
              Path(REAL_APPDATA) / "CleanListen" / "app" / "models" / R.MODEL_NAME):
        if d and (Path(d) / "model.onnx").exists():
            return Path(d)
    return None


@pytest.mark.skipif(not _real_model(), reason="the Kokoro voices aren't on this PC")
def test_every_voice_really_speaks(monkeypatch):
    # 1.15.0 before release: every British voice came out silent (espeak-ng has no "en-gb")
    pytest.importorskip("sherpa_onnx")
    monkeypatch.delenv("READALOUD_FAKE_VOICE")
    monkeypatch.setenv("READALOUD_MODEL", str(_real_model()))
    R._TTS.clear()
    try:
        for key, sid, name, _, accent in R.VOICES:
            x = R.say_text(R.voice_engine(accent, threads=4), "She waited by the old stone wall.", sid, 1.0)
            assert len(x) > R.SR, name           # over a second of speech
    finally:
        R._TTS.clear()


def test_every_voice_is_in_the_model():
    names = ("af_alloy,af_aoede,af_bella,af_heart,af_jessica,af_kore,af_nicole,af_nova,af_river,af_sarah,"
             "af_sky,am_adam,am_echo,am_eric,am_fenrir,am_liam,am_michael,am_onyx,am_puck,am_santa,bf_alice,"
             "bf_emma,bf_isabella,bf_lily,bm_daniel,bm_fable,bm_george,bm_lewis").split(",")
    for key, sid, *_ in R.VOICES:          # the model's own speaker numbers (its id2speaker)
        assert names[sid] == key
