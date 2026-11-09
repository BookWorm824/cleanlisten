"""Cancel goes back at once (the owner, 2026-11-09: "when clicking cancel on a book that just
started, it seems like it taking a while to actually cancel and go back to home screen").
CleanRead: the start page shows right away; the cancelled check stops at its next step by itself
and anything it still sends is dropped. CleanListen: Cancel during the Claude check goes straight
back to the list as it was, and a cancelled check's answer is dropped."""
import importlib.machinery
import importlib.util
import queue
import threading
import types

import pytest

from conftest import REPO


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.fixture
def cr():
    return load("cr_cancel_ui", "CleanRead.pyw")


@pytest.fixture
def cl():
    return load("cl_cancel_ui", "CleanListen.pyw")


def drain(ui, app):
    while not app.q.empty():
        ui.App._handle(app, app.q.get())


def cleanread_app(ui):
    app = types.SimpleNamespace(job=1, q=queue.Queue(), book=None, report=None, shown=[])
    app.show_setup = lambda: app.shown.append("start page")
    app.show_report = lambda: app.shown.append("report")
    app._send = lambda job, msg: ui.App._send(app, job, msg)
    app._load_book = lambda job, path: ui.App._load_book(app, job, path)
    return app


def fake_engine(ui, monkeypatch, go):
    class Book:
        def __init__(self, path):
            self.path, self.title = path, "The Test Book"

    def scan(book, use_ai=False, progress=None, cancel=None):
        progress(0.5, "AI is reading the book · 50%")
        go.wait(5)                           # the slow part (the AI loading, say)
        if cancel():
            raise KeyboardInterrupt
        return {"title": book.title}

    monkeypatch.setattr(ui.engine, "Book", Book)
    monkeypatch.setattr(ui.engine, "scan", scan)
    monkeypatch.setattr(ui.engine, "report_html", lambda res: "<html></html>")


def test_cleanread_cancel_goes_home_at_once(cr, monkeypatch, tmp_path):
    go = threading.Event()
    fake_engine(cr, monkeypatch, go)
    app = cleanread_app(cr)
    work = threading.Thread(target=cr.App._scan, args=(app, 1, str(tmp_path / "book.epub"), True))
    work.start()
    cr.App.cancel(app)
    assert app.shown == ["start page"] and app.job == 2      # before the work has stopped
    assert work.is_alive()
    go.set()
    work.join(5)
    drain(cr, app)
    assert app.shown == ["start page"]          # the cancelled check's messages are dropped
    assert app.book is None and app.report is None


def test_cleanread_check_that_isnt_cancelled_still_finishes(cr, monkeypatch, tmp_path):
    go = threading.Event()
    go.set()
    fake_engine(cr, monkeypatch, go)
    app = cleanread_app(cr)
    cr.App._scan(app, 1, str(tmp_path / "book.epub"), False)
    drain(cr, app)
    assert app.shown == ["report"] and app.report["title"] == "The Test Book"
    assert app.book.title == "The Test Book"
    assert (tmp_path / "book - Content Report.html").exists()


def test_cleanread_cancelled_check_doesnt_stop_the_next_one(cr, monkeypatch, tmp_path):
    go = threading.Event()
    fake_engine(cr, monkeypatch, go)
    app = cleanread_app(cr)
    old = threading.Thread(target=cr.App._scan, args=(app, 1, str(tmp_path / "old.epub"), True))
    old.start()
    cr.App.cancel(app)                 # job 2: the start page
    app.job = 3                        # Start pressed again (show_working moves on to job 3)
    go.set()
    old.join(5)
    cr.App._scan(app, 3, str(tmp_path / "new.epub"), False)
    drain(cr, app)
    assert app.shown == ["start page", "report"]
    assert str(app.book.path).endswith("new.epub")


def cleanlisten_app(cl):
    app = types.SimpleNamespace(claude_job=1, cancel_flag=False, page_name="working",
                                analysis={"scenes": ["as it was"]}, shown=[], saved=[])
    app.show_review = lambda *a, **k: app.shown.append("list")
    app._save_analysis = lambda: app.saved.append(app.analysis)
    return app


def test_cleanlisten_claude_check_cancel_goes_back_at_once(cl):
    app = cleanlisten_app(cl)
    cl.App.cancel(app)
    assert app.shown == ["list"] and app.claude_job == 2
    app.page_name = "review"
    # the cancelled check's answer arrives later: dropped, the list stays as it was
    cl.App._handle(app, ("claude_done", 1, {"scenes": ["changed by Claude"]}))
    cl.App._handle(app, ("claude_fail", "Claude stopped", 1))
    assert app.analysis == {"scenes": ["as it was"]} and app.shown == ["list"] and not app.saved


def test_cleanlisten_claude_check_answer_is_used(cl):
    app = cleanlisten_app(cl)
    cl.App._handle(app, ("claude_done", 1, {"scenes": ["changed by Claude"]}))
    assert app.analysis == {"scenes": ["changed by Claude"]}
    assert app.saved == [app.analysis] and app.shown == ["list"]


def test_cleanlisten_claude_works_on_a_copy():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert "work_on, workdir = copy.deepcopy(self.analysis), self.workdir" in src
    assert "cc.review(work_on, asr" in src
