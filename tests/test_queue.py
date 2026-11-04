"""The book queue (bookqueue.py, bookrunner.py and the "Your books" page), with the engine
stubbed: add, run, ready, review, save, cancel, crash and resume.

The worker tests start real worker processes running bookrunner.py, with a stand-in engine
(tests/stub_engine.py, chosen with CLEANLISTEN_ENGINE), so they're quick and need no speech
model or ffmpeg.
"""
import json
import os
import queue
import sys
import time
from pathlib import Path

import pytest

import bookqueue as BQ

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def spec(tmp_path, name="Book One", **kw):
    wd = tmp_path / "jobs" / name.replace(" ", "_")
    return dict({"audio": [str(tmp_path / name / "01.mp3")], "workdir": str(wd), "title": name,
                 "outdir": str(tmp_path / name / "Clean"), "groups": ["swearing"],
                 "filter_args": {"find_sex": True}, "use_ai": False, "use_claude": False,
                 "split": False, "summary": "Taking out: swearing."}, **kw)


# ---------------------------------------------------------------------------
# The list and its steps
# ---------------------------------------------------------------------------
def test_threads_are_shared_between_the_books_running_together():
    assert BQ.threads_each(1, cpus=16) == 8          # one book: at most 8
    assert BQ.threads_each(2, cpus=16) == 8
    assert BQ.threads_each(3, cpus=16) == 5
    assert BQ.threads_each(4, cpus=16) == 4
    assert BQ.threads_each(4, cpus=4) == 2           # never fewer than 2


def test_add_run_ready_review_save_done(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    assert q.at_once == 2                            # the default
    a, b, c = (q.add(spec(tmp_path, n)) for n in ("Book One", "Book Two", "Book Three"))
    assert [j["step"] for j in q.jobs] == [BQ.WAITING] * 3
    # two at once, in the order added
    assert [j["key"] for j in q.to_start()] == [a["key"], b["key"]]
    q.started(a["key"])
    q.started(b["key"])
    assert q.to_start() == []
    assert q.find(a["key"])["step"] == BQ.PREPARING

    assert q.handle(a["key"], {"p": 0.5, "m": "Listening to part 1 of 3"}) == "progress"
    assert q.find(a["key"])["status"] == "Listening to part 1 of 3"
    assert q.find(a["key"])["frac"] == 0.5
    q.handle(a["key"], {"log": "Listened to 01.mp3"})
    assert q.find(a["key"])["log"] == ["Listened to 01.mp3"]

    assert q.handle(a["key"], {"done": "ready", "found": {"words": 3, "passages": 1}}) == "step"
    a = q.find(a["key"])
    assert a["step"] == BQ.READY and a["found"]["words"] == 3
    assert q.handle(a["key"], {"exit": 0}) is None   # the worker ending after "done" is fine
    # a place is free: the third book starts
    assert [j["key"] for j in q.to_start()] == [c["key"]]
    q.started(c["key"])

    # reviewed: it waits to be saved, and saving goes ahead of preparing
    q.reviewed(a["key"])
    assert a["step"] == BQ.SAVE_WAITING
    q.add(spec(tmp_path, "Book Four"))
    q.handle(b["key"], {"done": "ready"})
    assert [j["key"] for j in q.to_start()] == [a["key"]]
    q.started(a["key"])
    assert a["step"] == BQ.SAVING and a["task"] == "save"
    q.handle(a["key"], {"done": "saved", "result": {"mutes": 3, "cuts": 1, "out": "x"}})
    assert a["step"] == BQ.DONE and a["result"]["mutes"] == 3

    # all of it was kept
    again = BQ.BookQueue(tmp_path / "queue.json")
    assert [j["step"] for j in again.jobs] == [BQ.DONE, BQ.READY, BQ.PREPARING, BQ.WAITING]
    again.clear_finished()
    assert [j["title"] for j in again.jobs] == ["Book Two", "Book Three", "Book Four"]


def test_books_at_once_is_kept(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    q.set_at_once(4)
    for n in range(5):
        q.add(spec(tmp_path, f"Book {n}"))
    assert len(q.to_start()) == 4
    assert BQ.BookQueue(tmp_path / "queue.json").at_once == 4
    q.set_at_once(9)                      # not a choice: back to the default
    assert q.at_once == 2


def test_resume_after_closing_or_an_update(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    a, b, c = (q.add(spec(tmp_path, n)) for n in ("Book One", "Book Two", "Book Three"))
    q.started(a["key"])
    q.handle(a["key"], {"p": 0.3, "m": "Listening to part 2 of 7"})
    q.started(b["key"])
    q.handle(b["key"], {"done": "ready"})
    q.reviewed(b["key"])
    q.started(b["key"])                    # saving when the window closed
    q.save()

    again = BQ.BookQueue(tmp_path / "queue.json")
    again.resume()
    steps = {j["title"]: j["step"] for j in again.jobs}
    assert steps == {"Book One": BQ.WAITING, "Book Two": BQ.SAVE_WAITING, "Book Three": BQ.WAITING}
    assert again.find(a["key"])["status"] == "Carries on where it left off"
    # it goes first again, and saving first of all
    assert [j["title"] for j in again.to_start()] == ["Book Two", "Book One"]


def test_the_same_book_again(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    a = q.add(spec(tmp_path))
    q.started(a["key"])
    with pytest.raises(BQ.Busy):            # being worked on right now
        q.add(spec(tmp_path))
    q.handle(a["key"], {"done": "ready"})
    b = q.add(spec(tmp_path, summary="Taking out: swearing, gore."))   # a re-check replaces it
    assert len(q.jobs) == 1 and q.jobs[0] is b and b["step"] == BQ.WAITING


def test_cancel_try_again_and_a_crash(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    a = q.add(spec(tmp_path))
    q.started(a["key"])
    q.stop(a["key"])
    assert a["step"] == BQ.STOPPED
    assert q.handle(a["key"], {"stopped": True}) is None    # already stopped
    assert q.remove(a["key"]) and not q.jobs

    b = q.add(spec(tmp_path, "Book Two"))
    q.started(b["key"])
    assert q.handle(b["key"], {"exit": 3221225477}) == "step"   # it crashed
    assert b["step"] == BQ.FAILED and "unexpectedly" in b["error"]
    assert q.remove(b["key"])             # a failed book can be removed
    b = q.add(spec(tmp_path, "Book Two"))
    q.started(b["key"])
    q.handle(b["key"], {"error": "The file couldn't be read"})
    assert b["step"] == BQ.FAILED and b["error"] == "The file couldn't be read"
    q.retry(b["key"])
    assert b["step"] == BQ.WAITING and "error" not in b

    # saving: Cancel goes back to ready to review; a failed save is tried again as a save
    q.started(b["key"])
    q.handle(b["key"], {"done": "ready"})
    q.reviewed(b["key"])
    q.started(b["key"])
    q.stop(b["key"])
    assert b["step"] == BQ.READY
    q.reviewed(b["key"])
    q.started(b["key"])
    q.handle(b["key"], {"error": "disk full"})
    q.retry(b["key"])
    assert b["step"] == BQ.SAVE_WAITING
    # a running book can't be removed
    q.started(b["key"])
    assert not q.remove(b["key"])


def test_move_up(tmp_path):
    q = BQ.BookQueue(tmp_path / "queue.json")
    for n in ("A", "B", "C"):
        q.add(spec(tmp_path, n))
    q.move(q.jobs[2]["key"], -1)
    assert [j["title"] for j in q.jobs] == ["A", "C", "B"]


def test_a_broken_queue_file_is_an_empty_queue(tmp_path):
    (tmp_path / "queue.json").write_text("{not json")
    assert BQ.BookQueue(tmp_path / "queue.json").jobs == []


# ---------------------------------------------------------------------------
# Worker processes (bookrunner.py) with a stand-in engine
# ---------------------------------------------------------------------------
@pytest.fixture
def workers(monkeypatch):
    monkeypatch.setenv("CLEANLISTEN_ENGINE", "stub_engine")
    monkeypatch.setenv("PYTHONPATH", str(HERE) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    got = queue.Queue()
    w = BQ.Workers(lambda key, msg: got.put((key, msg)), python=sys.executable)
    yield w, got
    w.stop_all(wait=2)


def wait_for(got, key, test, timeout=30):
    seen = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            k, msg = got.get(timeout=0.2)
        except queue.Empty:
            continue
        if k == key:
            seen.append(msg)
            if test(msg):
                return seen
    raise AssertionError(f"timed out; got {seen}")


def test_a_worker_prepares_then_saves_a_book(tmp_path, workers):
    w, got = workers
    q = BQ.BookQueue(tmp_path / "queue.json")
    job = q.add(spec(tmp_path, stub={"steps": 3}, split=True, m4b=True, cover="cover.jpg",
                     author="Kate Hunter", chapters_dir="Yoto", m4b_dir="Library", abs=True,
                     series="Hunter Files", series_no="2"))
    q.started(job["key"])
    w.start(job, "prepare", threads=4)
    seen = wait_for(got, job["key"], lambda m: "exit" in m)
    for m in seen:
        q.handle(job["key"], m)
    assert [m["p"] for m in seen if "p" in m] == [0.0, 0.5, 1.0]
    assert {"done": "ready", "found": {"words": 2, "passages": 1, "unticked": 1,
                                       "claude_note": ""}} in seen
    assert seen[-1] == {"exit": 0} and job["step"] == BQ.READY
    # the engine got the book's details and its share of the PC
    called = json.loads((Path(job["workdir"]) / "stub_called.json").read_text())
    assert called["threads"] == 4 and called["groups"] == ["swearing"] and called["find_sex"]
    assert called["title"] == "Book One"
    a = json.loads((Path(job["workdir"]) / "analysis.json").read_text())
    assert a["title"] == "Book One"

    # the review page unticked a word and saved the ticks; saving uses them
    a["mutes"][1]["on"] = False
    (Path(job["workdir"]) / "analysis.json").write_text(json.dumps(a))
    q.reviewed(job["key"])
    q.started(job["key"])
    w.start(job, "save", threads=4)
    seen = wait_for(got, job["key"], lambda m: "exit" in m)
    for m in seen:
        q.handle(job["key"], m)
    assert job["step"] == BQ.DONE
    assert job["result"] == {"mutes": 1, "cuts": 1, "cut_minutes": 0.1, "out": job["outdir"],
                             "chapters": None}
    # the book's own save choices (chapter files, one M4B with its cover and author)
    assert json.loads((Path(job["workdir"]) / "stub_render.json").read_text()) == {
        "chapters": True, "m4b": True, "cover": "cover.jpg", "author": "Kate Hunter",
        "chapters_dir": "Yoto", "m4b_dir": "Library", "abs_layout": True,
        "series": "Hunter Files", "series_no": "2"}


def test_cancel_stops_a_worker_and_keeps_what_it_heard(tmp_path, workers):
    w, got = workers
    job = dict(spec(tmp_path, stub={"steps": 10000, "delay": 0.05}), key="k1")
    w.start(job, "prepare", threads=2)
    wait_for(got, "k1", lambda m: m.get("p", 0) > 0)
    w.stop("k1")
    seen = wait_for(got, "k1", lambda m: "exit" in m)
    assert {"stopped": True} in seen and seen[-1] == {"exit": 0}
    assert (Path(job["workdir"]) / "transcript.json").exists()


def test_a_problem_in_one_book_is_reported(tmp_path, workers):
    w, got = workers
    job = dict(spec(tmp_path, stub={"fail": "The audio file is damaged"}), key="k2")
    w.start(job, "prepare", threads=2)
    seen = wait_for(got, "k2", lambda m: "exit" in m)
    assert {"error": "The audio file is damaged"} in seen
    assert "The audio file is damaged" in (Path(job["workdir"]) / "last_error.txt").read_text()


def test_a_crash_in_one_book_is_noticed(tmp_path, workers):
    w, got = workers
    q = BQ.BookQueue(tmp_path / "queue.json")
    job = q.add(spec(tmp_path, stub={"crash": True}))
    q.started(job["key"])
    w.start(job, "prepare", threads=2)
    for m in wait_for(got, job["key"], lambda m: "exit" in m):
        q.handle(job["key"], m)
    assert job["step"] == BQ.FAILED and "unexpectedly" in job["error"]


def test_two_books_run_side_by_side(tmp_path, workers):
    w, got = workers
    a = dict(spec(tmp_path, "Book A", stub={"steps": 20, "delay": 0.05}), key="a")
    b = dict(spec(tmp_path, "Book B", stub={"steps": 20, "delay": 0.05}), key="b")
    w.start(a, "prepare", threads=2)
    w.start(b, "prepare", threads=2)
    assert w.alive("a") and w.alive("b")
    done = set()
    end = time.monotonic() + 30
    while done != {"a", "b"} and time.monotonic() < end:
        try:
            k, m = got.get(timeout=0.2)
        except queue.Empty:
            continue
        if m.get("done") == "ready":
            done.add(k)
    assert done == {"a", "b"}


@pytest.mark.skipif(os.name != "nt", reason="the lock is Windows-only (msvcrt)")
def test_only_one_worker_per_book_at_a_time(tmp_path, workers):
    """A worker from before an update may still be finishing when the new copy starts the same
    book again: the new one waits for it."""
    w, got = workers
    old = dict(spec(tmp_path, stub={"steps": 10000, "delay": 0.05}), key="old")
    w.start(old, "prepare", threads=2)
    wait_for(got, "old", lambda m: m.get("p", 0) > 0)
    new = dict(old, key="new", stub={"steps": 2})
    w.start(new, "prepare", threads=2)
    wait_for(got, "new", lambda m: "Waiting for the last run" in m.get("m", ""))
    w.stop("old")
    seen = wait_for(got, "new", lambda m: "exit" in m)
    assert any(m.get("done") == "ready" for m in seen)


# ---------------------------------------------------------------------------
# The "Your books" page, with the workers stubbed
# ---------------------------------------------------------------------------
class FakeWorkers:
    """Stands in for the worker processes: the test says what each book's worker sends."""

    def __init__(self, app):
        self.app, self.procs, self.started, self.stopped = app, {}, [], []

    def start(self, job, task, threads):
        self.started.append((job["title"], task, threads))
        self.procs[job["key"]] = object()

    def send(self, key, **msg):
        self.app.q.put(("job", key, msg))
        if "done" in msg or "error" in msg or "stopped" in msg:
            self.procs.pop(key, None)

    def stop(self, key, wait=8.0):
        self.stopped.append(key)

    def stop_all(self, wait=5.0):
        self.procs.clear()


def _load_app():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("cleanlisten_gui", str(REPO / "CleanListen.pyw"))
    spec_ = importlib.util.spec_from_loader("cleanlisten_gui", loader)
    mod = importlib.util.module_from_spec(spec_)
    loader.exec_module(mod)
    return mod


def _pump(app, secs=0.4):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        app.update()
        time.sleep(0.02)


def test_the_your_books_page(tmp_path, monkeypatch):
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
        fake = FakeWorkers(app)
        app.workers = fake
        app.books = BQ.BookQueue(tmp_path / "queue.json")
        # two books added from the start page
        for name in ("Book One", "Book Two", "Book Three"):
            s = spec(tmp_path, name)
            Path(s["workdir"]).mkdir(parents=True)
            app.books.add(s)
        app._run_queue()
        app.show_queue()
        _pump(app)
        assert app.page_name == "queue"
        assert [t for t, task, _ in fake.started] == ["Book One", "Book Two"]
        assert all(task == "prepare" and th == BQ.threads_each(2) for _, task, th in fake.started)
        one, two, three = app.books.jobs
        fake.send(one["key"], p=0.4, m="Listening to part 1 of 2")
        _pump(app)
        assert app._rows[one["key"]]["status"].cget("text") == "Listening to part 1 of 2"
        assert int(app._rows[one["key"]]["pb"]["value"]) == 400

        # book one is ready: the third starts, and the row offers Review
        wd = Path(one["workdir"])
        (wd / "analysis.json").write_text(json.dumps(
            {"parts": one["audio"], "scenes": [], "groups": ["swearing"], "title": "Book One",
             "mutes": [{"id": 1, "part": 0, "s": 1.0, "e": 1.4, "cat": "mild", "src": "audio",
                        "word": "d**n", "ctx": "oh", "ctx_after": "it", "i": 0, "j": 1,
                        "on": True}]}))
        fake.send(one["key"], done="ready", found={"words": 1, "passages": 0})
        _pump(app)
        assert one["step"] == BQ.READY
        assert "1 word to mute" in app._rows[one["key"]]["status"].cget("text")
        assert fake.started[-1][0] == "Book Three"
        assert "ready to review" in app.title()

        # review it (one at a time, on the usual page), untick the word, and save
        app.review_job(one["key"])
        _pump(app)
        assert app.page_name == "review" and app.review_key == one["key"]
        app.mute_vars[0][0].set(False)
        app._save_from_review()
        _pump(app)
        assert app.page_name == "queue" and app.review_key is None
        assert one["step"] == BQ.SAVE_WAITING          # two are still being prepared
        saved = json.loads((wd / "analysis.json").read_text())
        assert saved["mutes"][0]["on"] is False and saved["mutes"][0]["by_you"]
        fake.send(two["key"], error="The audio file is damaged")
        _pump(app)
        assert two["step"] == BQ.FAILED
        assert fake.started[-1] == ("Book One", "save", BQ.threads_each(2))
        fake.send(one["key"], done="saved", result={"mutes": 0, "cuts": 0, "cut_minutes": 0,
                                                     "out": str(tmp_path)})
        _pump(app)
        assert one["step"] == BQ.DONE
        assert app._rows[one["key"]]["status"].cget("text").startswith("✓ Saved")

        # Cancel a book being prepared; "Books at once" is kept
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        app._cancel_book(three["key"])
        assert fake.stopped == [three["key"]] and three["step"] == BQ.STOPPED
        app._set_at_once(3)
        assert BQ.BookQueue(tmp_path / "queue.json").at_once == 3
        # the start page shows the books, and Back from a review goes to them
        app._add_book()
        _pump(app)
        assert app.page_name != "queue"
    finally:
        app.destroy()


def test_try_again_right_after_cancel(tmp_path, workers):
    """The old worker may still be finishing when the book is started again: only the new
    worker's messages count, so its last "stopped" doesn't stop the new run."""
    w, got = workers
    q = BQ.BookQueue(tmp_path / "queue.json")
    job = q.add(spec(tmp_path, stub={"steps": 10000, "delay": 0.05}))
    q.started(job["key"])
    w.start(job, "prepare", threads=2)
    wait_for(got, job["key"], lambda m: m.get("p", 0) > 0)
    w.stop(job["key"])
    q.stop(job["key"])
    q.retry(job["key"])
    q.started(job["key"])
    job["stub"] = {"steps": 2}
    w.start(job, "prepare", threads=2)
    for m in wait_for(got, job["key"], lambda m: "exit" in m):
        assert "stopped" not in m
        q.handle(job["key"], m)
    assert job["step"] == BQ.READY


def test_a_worker_notices_the_window_has_gone():
    import subprocess
    import bookrunner
    assert not bookrunner.window_gone(os.getpid())
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert bookrunner.window_gone(gone.pid)


# "bad allocation" (2026-11-04): two books at once ran a smaller PC out of memory
def test_one_book_at_a_time_on_a_pc_with_little_memory(tmp_path, monkeypatch):
    assert BQ.default_at_once(8) == 1 and BQ.default_at_once(16) == 2
    assert BQ.default_at_once(0) == 2                    # can't tell: as before
    monkeypatch.setattr(BQ, "memory_gb", lambda: 8)
    q = BQ.BookQueue(tmp_path / "queue.json")
    assert q.at_once == 1
    # 1.14.0-1.14.3 saved 2 without being asked: a small PC goes down to 1
    (tmp_path / "queue.json").write_text('{"at_once": 2, "jobs": []}')
    assert BQ.BookQueue(tmp_path / "queue.json").at_once == 1
    # their own choice is kept, also 2
    q.set_at_once(2)
    assert BQ.BookQueue(tmp_path / "queue.json").at_once == 2
    (tmp_path / "queue.json").write_text('{"at_once": 3, "jobs": []}')     # chose 3 before
    assert BQ.BookQueue(tmp_path / "queue.json").at_once == 3


def test_running_out_of_memory_is_said_plainly():
    for raw in ("bad allocation", "std::bad_alloc", "MemoryError", "Unable to allocate 2.1 GiB",
                "[ONNXRuntimeError] : 6 : Failed to allocate memory",
                "[WinError 1455] The paging file is too small for this operation to complete",
                "[WinError 1450] Insufficient system resources exist to complete the requested service",
                "[WinError 8] Not enough storage is available to process this command"):
        assert BQ.plain_error(raw) == BQ.OUT_OF_MEMORY
    assert "Books at once" in BQ.OUT_OF_MEMORY and "allocation" not in BQ.OUT_OF_MEMORY
    assert BQ.plain_error("Couldn't save Part 1.mp3") == "Couldn't save Part 1.mp3"
    assert BQ.plain_error(None) == ""
