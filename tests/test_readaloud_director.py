"""ReadAloud 1.16: PDFs read as a story, and the reading director (readaloud_ai).

Lauren, 2026-11-06, after Vermilion.pdf (a scanned 1981 book): "it reads things its not supposed
too, and its very stilted ... maybe have claude or chat go through the book - remove anything that
shouldn't be read, look at the context of the book and give the reading directions"."""
import json
import os
import re
from pathlib import Path

import pytest

os.environ["READALOUD_FAKE_VOICE"] = "1"
import readaloud as R  # noqa: E402
import readaloud_ai as A  # noqa: E402
from test_readaloud import STORY, _probe, make_epub, needs_ffmpeg  # noqa: E402


# ---------- PDFs ----------
def make_pdf(path, pages):
    """A small PDF, one list of printed lines per page (Helvetica), the way a scanned book's text
    layer looks to pypdf."""
    objs = []

    def add(body):
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objs) + 2 * len(pages) + 1
    kids = []
    for lines in pages:
        esc = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
        stream = ("BT /F1 10 Tf 14 TL 50 750 Td " + " ".join(f"({x}) '" for x in esc) + " ET").encode("latin-1")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] /Contents {c} 0 R "
                        f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()))
    add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode())
    cat = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    info = add(b"<< /Title (Vermilion) /Author (Whitney, Phyllis A., 1903-2008) >>")
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {cat} 0 R /Info {info} 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    Path(path).write_bytes(bytes(out))
    return path


WORDS = ("the wind came down off the red rocks and the light went gold across the wash while she "
         "waited by the old stone wall for the letter that never came").split()


def story_lines(n, start=0):
    return [" ".join(WORDS[(start + 11 * i + j) % len(WORDS)] for j in range(11)) for i in range(n)]


def scanned_book():
    """Title page, copyright, chapter 1 (a short page without the running head), two full pages
    with heads and page numbers, chapter 2, two more pages, then the back of the jacket."""
    pages = [["VERMILION"], ["Copyright 1981 by Phyllis A. Whitney", "All Rights Reserved"]]
    no = [1]

    def page(lines, head=True):
        no[0] += 1
        top = f"Phyllis A. Whitney {no[0]}" if no[0] % 2 else f"{no[0]} Vermilion"
        pages.append(([top] if head else []) + lines)

    page(["The first step that would take me to Arizona began at the time of",
          "Jed Phillips' murder, and nothing about it was ever simple for me."]
         + story_lines(3) + ["it was over at last."], head=False)
    body = story_lines(12, 7)
    body[4] += " know-"
    body[5] = "ing " + body[5]
    body[7] = "and so it ended."
    page(body)
    for k in range(4):
        page(story_lines(12, 30 + 7 * k))
    page(["I stood on the high strip of deck that ran outside the guest-",
          "house and stared at rock formations towering across the wash."]
         + story_lines(3, 50) + ["then she was gone."], head=False)
    for k in range(4):
        page(story_lines(12, 70 + 5 * k))
    pages.append(["(continued from front flap)", "In Sedona there is an immediate clash with her sister."])
    return pages


def test_a_scanned_pdf_reads_as_a_story(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(R, "_WORDS", {"knowing", "know", "ing", "guest", "house", "the", "wind"})
    b = R.load_book(make_pdf(tmp_path / "Vermilion.pdf", scanned_book()))
    assert (b["title"], b["author"]) == ("Vermilion", "Phyllis A. Whitney")
    assert [(c["title"], c["read"]) for c in b["chapters"]] == [
        ("Front matter (jacket, title page, copyright)", False), ("Chapter 1", True),
        ("Chapter 2", True), ("Book jacket", False)]
    text = " ".join(t for c in b["chapters"][1:3] for _, t in c["paras"])
    assert "Whitney" not in text and "Vermilion" not in text            # no running heads
    assert not re.search(r"\b\d+\b", text)                               # no page numbers
    assert "knowing" in text and "guest-house" in text                  # mended at line ends
    first = b["chapters"][1]["paras"]
    assert first[0][1].startswith("The first step") and first[0][1].endswith("it was over at last.")
    assert any(p[1].endswith("and so it ended.") for p in first)        # a real paragraph end


def test_words_split_or_glued_by_scanning_are_mended(monkeypatch):
    monkeypatch.setattr(R, "_WORDS", {"knowing", "know", "high", "heeled", "in", "my", "of", "that", "ear",
                                      "but", "now", "with", "whom", "been", "she'd", "wait", "asking"})
    assert R.mend_words("without ever know- ing it") == "without ever knowing it"
    assert R.mend_words("high- heeled boots") == "high-heeled boots"
    assert R.mend_words("wait- ing for him") == "waiting for him"       # not in the word list: joined
    assert R.unglue("asking inmy ear, ofthat, butnow, withwhom she'dbeen") == \
        "asking in my ear, of that, but now, with whom she'd been"
    assert R.unglue("/ was Jed's daughter") == "I was Jed's daughter"
    assert R.unglue("Tlaquepaque") == "Tlaquepaque"                       # names are left alone
    assert R.mend_paragraphs([["p", "the woman who"], ["p", "hadn't wanted me."], ["p", "Next."]]) == \
        [["p", "the woman who hadn't wanted me."], ["p", "Next."]]


@needs_ffmpeg
def test_carry_on_after_stop_for_now_reads_everything(tmp_path, monkeypatch):
    # 1.15.0: "Stop for now" left its stop note, so Carry on stopped every chapter at once and
    # then tried to put the book together without them
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    b = R.load_book(make_epub(tmp_path / "book.epub", STORY))
    jobdir = R.start_job(b, "af_heart", 1.0, [1, 2], tmp_path / "out.m4b")
    (jobdir / "stop").write_text("stop")
    res = R.Maker(jobdir, workers=(1, 1)).run()
    assert Path(res["file"]).exists()
    assert len(_probe(tmp_path / "out.m4b", "-show_chapters")["chapters"]) == 2


# ---------- the reading director ----------
def test_speech_and_narration_are_split():
    assert A.split_quotes('"I won\'t," she said. "Never."') == \
        [(True, '"I won\'t,"'), (False, "she said."), (True, '"Never."')]
    # a long speech carries on into the next paragraph without a closing quote
    assert A.split_quotes('He sighed. "It was long ago, and') == \
        [(False, "He sighed."), (True, '"It was long ago, and')]
    assert A.split_quotes("No speech here.") == [(False, "No speech here.")]


def test_a_fix_must_keep_the_words():
    assert A.same_words("Jed came out wth a few broken bones", "Jed came out with a few broken bones")
    assert not A.same_words("Jed came out wth a few broken bones that mended", "Jed was hurt.")


class FakeAI:
    """Stands in for cleanlisten_claude: canned answers for the cast and the parts."""
    NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}
    PROVIDER = "claude"

    class ClaudeError(Exception):
        pass

    def __init__(self):
        self.asked = []

    def name(self, provider=None):
        return "Claude"

    def run(self, prompt, system, schema=None, timeout=0, **kw):
        self.asked.append(prompt)
        if "first_person" in schema["properties"]:
            return {"data": {"first_person": True, "narrator_name": "Lindsay", "notes": "Quiet suspense.",
                             "characters": [{"name": "Lindsay", "gender": "female", "age": "adult"},
                                            {"name": "Rick", "gender": "male", "age": "adult"}],
                             "pronounce": [{"word": "Tlaquepaque", "say": "tlah-keh-pah-keh"},
                                           {"word": "Sybil", "say": "sib-ul"}]}}
        out = []
        for n, text in re.findall(r"^\[(\d+)\](?: \(heading\))? (.*)$", prompt, re.M):
            d = {"n": int(n), "skip": False, "fix": "", "pause": "normal", "pace": "normal", "mood": "",
                 "speakers": []}
            if "Whitney 11" in text or text.startswith("The story went on"):
                d["skip"] = True
            elif "Tlaquepaque" in text:
                d.update(pause="scene", pace="slower", mood="sad")
            elif "all right" in text:
                d.update(fix='"Are you all right?" Rick asked. "I am," I said.', speakers=["Rick", "Lindsay"])
            else:
                continue
            out.append(d)
        return {"data": {"characters": [], "pronounce": [], "paragraphs": out}}


DIRECTED = [("Chapter One", ["Phyllis A. Whitney 11", "She went to Tlaquepaque in the rain.",
                             '"Are you all right?" Rick asked. "I am," 1 said.'])]


def test_the_director_marks_how_to_read(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(R, "_WORDS", {"sybil", "she", "went", "to"})
    fake = FakeAI()
    monkeypatch.setattr(A, "cc", lambda: fake)
    b = R.load_book(make_epub(tmp_path / "b.epub", DIRECTED, series=False, cover=False))
    jobdir = R.start_job(b, "af_heart", 1.0, [1], tmp_path / "out.m4b", {"director": "claude", "cast": True})
    s = A.direct(jobdir)
    assert s["skipped"] == 1 and s["fixed"] == 1
    paras = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[0]["paras"]
    assert "Phyllis A. Whitney 11" not in [p[1] for p in paras]          # page furniture left out
    sad = next(p for p in paras if p[1].startswith("She went"))
    assert sad[2] == {"s": A.PACE["slower"], "g": A.PAUSE["scene"]}
    rick = next(p for p in paras if p[1] == '"Are you all right?"')
    assert R.VOICE[rick[2]["v"]][3].startswith("American man")          # Rick: a man's voice
    me = next(p for p in paras if p[1] == '"I am,"')
    assert "v" not in (me[2] if len(me) > 2 else {})                     # the narrator's own line
    job = json.loads((jobdir / "job.json").read_text(encoding="utf8"))
    assert job["pronounce"] == {"Tlaquepaque": "tlah-keh-pah-keh"}        # not "Sybil": the voice knows it
    assert "Left out (1)" in (jobdir / "report.txt").read_text(encoding="utf8")
    # asked once: starting again (another voice, or Carry on) uses the kept answers
    n = len(fake.asked)
    jobdir = R.start_job(b, "af_heart", 1.0, [1], tmp_path / "out.m4b", {"director": "claude", "cast": False})
    A.direct(jobdir)
    assert len(fake.asked) == n
    paras = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[0]["paras"]
    assert not any(len(p) > 2 and "v" in p[2] for p in paras)            # no character voices this time


def test_a_long_paragraph_is_never_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    fake = FakeAI()
    monkeypatch.setattr(A, "cc", lambda: fake)
    long_story = [("Chapter One", [" ".join(["The story went on and on."] * 40), "Short.", "Shorter."])]
    b = R.load_book(make_epub(tmp_path / "b.epub", long_story, series=False, cover=False))
    jobdir = R.start_job(b, "af_heart", 1.0, [1], tmp_path / "out.m4b", {"director": "claude"})
    assert A.direct(jobdir)["skipped"] == 0
    paras = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[0]["paras"]
    assert paras[1][1].startswith("The story went on")


@needs_ffmpeg
def test_a_directed_book_is_read_with_its_voices(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(A, "cc", lambda: FakeAI())
    b = R.load_book(make_epub(tmp_path / "b.epub", DIRECTED, series=False, cover=False))
    jobdir = R.start_job(b, "bf_emma", 1.0, [1], tmp_path / "out.m4b", {"director": "claude", "cast": True})
    res = R.Maker(jobdir, workers=(1, 1)).run()
    assert Path(res["file"]).exists() and res["report"] and Path(res["report"]).exists()
    paras = json.loads((jobdir / "chapters.json").read_text(encoding="utf8"))[0]["paras"]
    rick = next(p for p in paras if p[1] == '"Are you all right?"')
    assert R.VOICE[rick[2]["v"]][4] == "gb"                              # same accent as the narrator


def test_the_director_ships():
    files = json.loads((Path(R.__file__).parent / "version.json").read_text())["files"]
    assert "readaloud_ai.py" in files
