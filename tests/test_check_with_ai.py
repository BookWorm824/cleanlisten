"""A button to check a book again with Claude, ChatGPT or Gemini (the owner, 2026-11-14: books
done overnight came back with Claude never having checked them, and "you need a button that I can
hit to just check the book again with claude/chat/Gemini"; "have it say claude if thats whats used,
chat if thats whats used"; "check with ai sounds like what we already did").

On "Your books" each ready book has "Check with Claude" (one at a time or "Check all N"), run in
the background like any book; the review page says plainly, in yellow, when it didn't check."""
import json
import sys
import types
from pathlib import Path

import pytest

import bookqueue as BQ
from test_queue import FakeWorkers, _load_app, _pump, spec


def _ready(q, tmp_path, name="Book One", **kw):
    job = q.add(spec(tmp_path, name, use_claude=True, **kw))
    q.started(job["key"])
    q.handle(job["key"], {"done": "ready", "found": {"words": 1, "passages": 2,
                                                     "claude_checked": False, "claude_wanted": True}})
    return job


def test_a_ready_book_goes_in_line_to_be_checked_and_comes_back_ready(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json", at_once=1)
    job = _ready(q, tmp_path)
    assert q.check(job["key"]) is job
    assert job["step"] == BQ.WAITING and job["status"] == BQ.CHECK_WAITING
    assert q.to_start() == [job]
    q.started(job["key"])
    assert job["task"] == "check" and job["step"] == BQ.PREPARING
    q.handle(job["key"], {"done": "ready", "found": {"words": 1, "passages": 0, "claude_checked": True}})
    assert job["step"] == BQ.READY and "check_only" not in job and job["found"]["claude_checked"]
    # kept across closing the window
    assert BQ.BookQueue(tmp_path / "queue.json").find(job["key"])["found"]["claude_checked"]


def test_a_check_that_is_stopped_or_fails_leaves_the_review_as_it_was(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json", at_once=1)
    job = _ready(q, tmp_path)
    q.check(job["key"])
    q.stop(job["key"])                                   # Cancel while waiting
    assert job["step"] == BQ.READY and "check_only" not in job
    q.check(job["key"])
    q.started(job["key"])
    q.handle(job["key"], {"error": "You've reached your plan's limit"})
    assert job["step"] == BQ.READY                       # not "Ran into a problem": still reviewable
    assert job["found"]["check_failed"] and "plan's limit" in job["found"]["claude_note"]
    assert job["found"]["words"] == 1                    # what it found is still there
    q.check(job["key"])
    q.started(job["key"])
    q.handle(job["key"], {"exit": 1})                    # the worker crashed
    assert job["step"] == BQ.READY
    # a book that was being prepared still fails as before
    other = q.add(spec(tmp_path, "Book Two"))
    q.started(other["key"])
    q.handle(other["key"], {"error": "The audio file is damaged"})
    assert other["step"] == BQ.FAILED


def test_the_worker_checks_without_listening_again(tmp_path, monkeypatch):
    import bookrunner
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "analysis.json").write_text(json.dumps({"parts": ["a.mp3"], "scenes": [], "mutes": [
        {"id": 1, "part": 0, "s": 1.0, "e": 1.2, "on": True}], "claude_wanted": True}))
    seen = {}

    def review(st, asr, progress=None, cancel=None):
        seen.update(asr=asr, cancel=cancel())
        progress(0.5, "The AI is reading the book · section 1 of 2")
        st.update(claude_checked=True, claude_note="It read the whole book.")
        st["mutes"][0]["on"] = False

    monkeypatch.setitem(sys.modules, "cleanlisten_claude", types.SimpleNamespace(review=review))
    sent = []
    monkeypatch.setattr(bookrunner, "send", lambda **m: sent.append(m))
    engine = types.SimpleNamespace(load_asr=lambda w, parts: [{"t": "hi", "part": 0}],
                                   write_safely=lambda p, t: Path(p).write_text(t))
    said = []
    bookrunner.check(engine, {"workdir": str(wd), "task": "check"},
                     types.SimpleNamespace(is_set=lambda: False), lambda f, m: said.append(m),
                     lambda m: None)
    assert seen == {"asr": [{"t": "hi", "part": 0}], "cancel": False}
    st = json.loads((wd / "analysis.json").read_text())
    assert st["claude_checked"] and st["mutes"][0]["on"] is False
    assert sent[-1]["done"] == "ready"
    assert sent[-1]["found"]["claude_checked"] is True and sent[-1]["found"]["words"] == 0
    assert said == ["The AI is reading the book · section 1 of 2"]


class FakeCC:
    PROVIDER = "chatgpt"

    @staticmethod
    def name(provider=None):
        return "ChatGPT"

    @staticmethod
    def status(provider=None):
        return "ok"


def _buttons(w):
    out = []
    for c in w.winfo_children():
        try:
            if c.winfo_class() in ("TButton", "Button"):
                out.append(c.cget("text"))
        except Exception:
            pass
        out += _buttons(c)
    return out


def _labels(w):
    out = []
    for c in w.winfo_children():
        if c.winfo_class() == "Label":
            out.append(c.cget("text"))
        out += _labels(c)
    return out


def test_your_books_and_the_review_page_name_the_one_in_use(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    gui = _load_app()
    monkeypatch.setattr(gui, "QUEUE", tmp_path / "queue.json")
    monkeypatch.setattr(gui, "RESUME", tmp_path / "resume.json")
    monkeypatch.setattr(gui, "chime", lambda: None)
    monkeypatch.setattr(gui.freezes.Watch, "offer", lambda self: None)
    try:
        app = gui.App()
    except tk.TclError as ex:
        pytest.skip(f"no display ({ex})")
    try:
        app.withdraw()
        app._cc = lambda: FakeCC
        app.claude_state = "ok"
        fake = FakeWorkers(app)
        app.workers = fake
        app.books = BQ.BookQueue(tmp_path / "queue.json", at_once=1)
        jobs = []
        for name in ("Book One", "Book Two"):
            s = spec(tmp_path, name, use_claude=True)
            Path(s["workdir"]).mkdir(parents=True)
            # prepared by an earlier CleanListen: the list doesn't know yet whether it was checked
            (Path(s["workdir"]) / "analysis.json").write_text(json.dumps(
                {"parts": s["audio"], "scenes": [], "groups": ["swearing"], "title": name,
                 "sentences": [[0, 0]],
                 "mutes": [{"id": 1, "part": 0, "s": 1.0, "e": 1.4, "cat": "mild", "src": "audio",
                            "word": "d**n", "ctx": "oh", "ctx_after": "it", "i": 0, "j": 1,
                            "on": True}]}))
            job = app.books.add(s)
            app.books.started(job["key"])
            app.books.handle(job["key"], {"done": "ready", "found": {"words": 1, "passages": 0}})
            jobs.append(job)
        app.show_queue()
        _pump(app)
        one, two = jobs
        assert "Not checked by ChatGPT yet." in app._rows[one["key"]]["status"].cget("text")
        page = _buttons(app)
        assert page.count("Check with ChatGPT") == 2 and "Check all 2 with ChatGPT" in page
        assert not any("AI" in b for b in page)

        # the review page: a yellow line saying so, with the button
        app.review_job(one["key"])
        _pump(app)
        assert any(t.startswith("ChatGPT didn't check this book") for t in _labels(app))
        assert "Check with ChatGPT" in _buttons(app)
        assert "Check everything with AI" not in _buttons(app)
        app._back_to_start()
        _pump(app)

        # Check all: both go in line, one at a time (Books at once: 1), as checks
        app._check_books([one["key"], two["key"]])
        _pump(app)
        assert fake.started[-1][:2] == ("Book One", "check")
        assert two["step"] == BQ.WAITING
        assert app._rows[two["key"]]["status"].cget("text") == BQ.CHECK_WAITING
        fake.send(one["key"], p=0.3, m="The AI is reading the book · section 1 of 3")
        _pump(app)
        assert "section 1 of 3" in app._rows[one["key"]]["status"].cget("text")
        fake.send(one["key"], done="ready", found={"words": 0, "passages": 0, "claude_checked": True,
                                                   "claude_wanted": True})
        _pump(app)
        assert one["step"] == BQ.READY and fake.started[-1][:2] == ("Book Two", "check")
        assert "Not checked" not in app._rows[one["key"]]["status"].cget("text")
        assert "Check again with ChatGPT" in _buttons(app)
        # it couldn't: the book is still ready to review, and says so
        fake.send(two["key"], error="ChatGPT stopped without an answer")
        _pump(app)
        assert two["step"] == BQ.READY
        assert "ChatGPT couldn't check it" in app._rows[two["key"]]["status"].cget("text")
    finally:
        app.destroy()


def test_a_book_checked_on_its_review_page_shows_as_checked_on_the_list(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    gui = _load_app()
    monkeypatch.setattr(gui, "QUEUE", tmp_path / "queue.json")
    monkeypatch.setattr(gui, "RESUME", tmp_path / "resume.json")
    monkeypatch.setattr(gui, "chime", lambda: None)
    monkeypatch.setattr(gui.freezes.Watch, "offer", lambda self: None)
    try:
        app = gui.App()
    except tk.TclError as ex:
        pytest.skip(f"no display ({ex})")
    try:
        app.withdraw()
        app._cc = lambda: FakeCC
        app.claude_state = "ok"
        app.workers = FakeWorkers(app)
        app.books = BQ.BookQueue(tmp_path / "queue.json", at_once=1)
        s = spec(tmp_path, "Book One", use_claude=True)
        Path(s["workdir"]).mkdir(parents=True)
        (Path(s["workdir"]) / "analysis.json").write_text(json.dumps(
            {"parts": s["audio"], "scenes": [], "mutes": [], "groups": ["swearing"],
             "sentences": [[0, 0]], "claude_wanted": True}))
        job = app.books.add(s)
        app.books.started(job["key"])
        app.books.handle(job["key"], {"done": "ready", "found": {"words": 0, "passages": 0,
                                                                "claude_checked": False}})
        app.review_job(job["key"])
        _pump(app)
        app.analysis.update(claude_checked=True, claude_note="It read the whole book.")
        app._back_to_start()
        _pump(app)
        assert job["found"]["claude_checked"] is True
        assert "Not checked" not in app._rows[job["key"]]["status"].cget("text")
    finally:
        app.destroy()


def test_a_book_started_without_it_still_offers_the_check_once_it_is_signed_in(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    gui = _load_app()
    monkeypatch.setattr(gui, "QUEUE", tmp_path / "queue.json")
    monkeypatch.setattr(gui, "RESUME", tmp_path / "resume.json")
    monkeypatch.setattr(gui, "chime", lambda: None)
    monkeypatch.setattr(gui.freezes.Watch, "offer", lambda self: None)
    try:
        app = gui.App()
    except tk.TclError as ex:
        pytest.skip(f"no display ({ex})")
    try:
        app.withdraw()
        app._cc = lambda: FakeCC
        app.workers = FakeWorkers(app)
        app.books = BQ.BookQueue(tmp_path / "queue.json", at_once=1)
        s = spec(tmp_path, "Book One")                    # use_claude False ("Start without it?")
        Path(s["workdir"]).mkdir(parents=True)
        (Path(s["workdir"]) / "analysis.json").write_text(json.dumps(
            {"parts": s["audio"], "scenes": [], "mutes": [], "groups": ["swearing"]}))
        job = app.books.add(s)
        app.books.started(job["key"])
        app.books.handle(job["key"], {"done": "ready", "found": {"words": 0, "passages": 0}})
        app.claude_state = None                           # not set up on this PC: nothing said
        app.show_queue()
        _pump(app)
        assert "Not checked" not in app._rows[job["key"]]["status"].cget("text")
        app.claude_state = "ok"                           # signed in now
        app.show_queue()
        _pump(app)
        assert "Not checked by ChatGPT yet." in app._rows[job["key"]]["status"].cget("text")
        assert "Check with ChatGPT" in _buttons(app)
    finally:
        app.destroy()
