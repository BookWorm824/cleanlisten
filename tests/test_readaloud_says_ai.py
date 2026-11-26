"""ReadAloud's reading director says just "the AI" on screen and in its report, never Claude,
ChatGPT or Gemini by name (the owner, 2026-11-26: "where it says claude is orchestrating and
such it needs to say just AI"). Setting up and signing in still name the one chosen."""
import re
from pathlib import Path

import readaloud_ai

HERE = Path(__file__).resolve().parent.parent
NAMES = ("Claude", "ChatGPT", "Gemini")


def test_progress_and_errors_say_the_ai():
    src = (HERE / "readaloud_ai.py").read_text(encoding="utf8")
    assert "lib.name()" not in src
    assert 'who = "The AI"' in src
    for msg in ("is getting to know the book", "is looking up how to say the names",
                "is going through the book and marking how to read it"):
        assert msg in src
    assert "The AI couldn't go through the book" in src
    assert "The AI couldn't look up the names" in src


def test_progress_messages_while_directing(tmp_path, monkeypatch):
    said = []

    class Lib:
        NAMES = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}
        PROVIDER = "claude"

        @staticmethod
        def name():
            return "Claude"

    monkeypatch.setattr(readaloud_ai, "cc", lambda: Lib)
    monkeypatch.setattr(readaloud_ai, "direction_dir", lambda: tmp_path)

    class Seen(Exception):
        pass

    def stop_here(*a, **k):
        raise Seen()
    monkeypatch.setattr(readaloud_ai, "cast", stop_here)
    src = (HERE / "readaloud_ai.py").read_text(encoding="utf8")
    m = re.search(r"\ndef (direct)\(jobdir, progress", src)
    assert m
    job = tmp_path / "job"
    job.mkdir()
    (job / "job.json").write_text('{"title": "T", "director": "claude"}', encoding="utf8")
    (job / "chapters.json").write_text('[{"title": "1", "paras": ["Hello."], "words": 1}]',
                                       encoding="utf8")
    try:
        getattr(readaloud_ai, m.group(1))(job, lambda f, msg: said.append(msg), None, None)
    except Seen:
        pass
    assert said and said[0].startswith("The AI ")
    assert not any(n in s for s in said for n in NAMES)


def test_report_says_the_ai(tmp_path):
    rep = {"voices": {}, "pronounce": {}, "skipped": [], "fixed": [], "ignored": []}
    readaloud_ai.write_report(tmp_path, {"title": "Truth Be Told", "director": "claude"}, {}, rep)
    text = (tmp_path / "report.txt").read_text(encoding="utf8")
    assert text.startswith("Truth Be Told — what the AI changed before ReadAloud read it")
    assert not any(n in text for n in NAMES)
