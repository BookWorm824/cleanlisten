"""ReadAloud updates without being closed (the owner, 2026-11-20: "also need update without closing
the program"): "Check for updates" on every page and F5, a quiet look every 30 minutes that turns the
link into "Update now", and after the update it opens again where it was: the same book and step, or
the book being read carries on by itself. The update server is a stand-in here."""
import json
import threading
import time

from test_readaloud import STORY, make_epub
from test_readaloud_look import _pump, window  # noqa: F401  (the window, see-through)


class FakeLauncher:
    def __init__(self, remote="99.0.0", fail=None):
        self.remote, self.fail, self.updated = remote, fail, False

    def remote_version(self, timeout=4):
        if self.fail:
            raise OSError(self.fail)
        return {"version": self.remote}

    @staticmethod
    def _ver(v):
        return tuple(int(x) for x in v.split("."))

    def update(self, arg=None):
        self.updated = True
        return self.remote


def _until(app, cond, sec=5):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _restart_catcher(win, app, monkeypatch):
    started, gone = [], []
    monkeypatch.setattr(win.subprocess, "Popen", lambda cmd, **k: started.append((cmd, k.get("env") or {})))
    app.destroy = lambda: gone.append(True)          # (taken off again before the window goes)
    return started, gone


def test_every_page_has_check_for_updates(window):
    win, app = window
    ver = win.app_version()
    assert app.upd_link.label.cget("text") == f"v{ver} · Check for updates"     # the start page
    app._new_page("Narrating the book…")
    assert app._upd_lbl.cget("text") == f"v{ver} · Check for updates"           # every other page
    assert app.bind_all("<F5>")                                                  # and F5


def test_no_update_says_so(window, monkeypatch):
    win, app = window
    monkeypatch.setattr(app, "_launcher", lambda: FakeLauncher(remote="0.0.1"))
    started, gone = _restart_catcher(win, app, monkeypatch)
    try:
        app.check_updates()
        assert _until(app, lambda: "latest version" in app.upd_link.label.cget("text"))
        assert not started and not gone
    finally:
        del app.destroy


def test_it_updates_and_opens_again_on_the_same_book_and_step(window, tmp_path, monkeypatch):
    win, app = window
    fake = FakeLauncher()
    monkeypatch.setattr(app, "_launcher", lambda: fake)
    started, gone = _restart_catcher(win, app, monkeypatch)
    try:
        app.book_path = str(make_epub(tmp_path / "book.epub", STORY))
        app.steps_page.go(3)
        app.series_var.set("Grace Ford")
        app.check_updates()
        assert _until(app, lambda: gone)
        assert fake.updated
        cmd, env = started[0]
        assert cmd[1].endswith("launcher.pyw") and cmd[2] == "aloud"
        assert env["CLEANLISTEN_UPDATE_DONE"] == "1" and "99.0.0" in env["CLEANLISTEN_UPDATED"]
        carry = json.loads(env["READALOUD_CARRY_ON"])
        assert carry["book"] == app.book_path and carry["step"] == 3 and carry["series"] == "Grace Ford"
    finally:
        del app.destroy


def test_the_quiet_look_only_says_an_update_is_ready(window, monkeypatch):
    win, app = window
    fake = FakeLauncher()
    monkeypatch.setattr(app, "_launcher", lambda: fake)
    monkeypatch.setattr(app, "UPDATE_EVERY", 10 ** 8)
    app._auto_check()
    assert _until(app, lambda: "Update now" in app.upd_link.label.cget("text"))
    assert app.upd_link.label.cget("text") == "ReadAloud 99.0.0 is ready · Update now"
    assert not fake.updated                          # nothing fetched until it's pressed
    app.show_setup()
    assert app.upd_link.label.cget("text") == "ReadAloud 99.0.0 is ready · Update now"


class FakeMaker:
    paused = False

    def __init__(self, jobdir):
        self.jobdir, self.stopped = jobdir, threading.Event()

    def stop(self):
        self.stopped.set()


def test_a_book_being_read_carries_on_after_the_update(window, tmp_path, monkeypatch):
    win, app = window
    fake = FakeLauncher()
    monkeypatch.setattr(app, "_launcher", lambda: fake)
    monkeypatch.setattr(win.messagebox, "askyesno", lambda *a, **k: True)
    started, gone = _restart_catcher(win, app, monkeypatch)
    try:
        app.maker, app.job_title = FakeMaker(tmp_path / "job"), "Nearly Safe"
        app.check_updates()
        assert _until(app, lambda: gone)
        assert app.maker is None or app.maker.stopped.is_set()
        carry = json.loads(started[0][1]["READALOUD_CARRY_ON"])
        assert carry == {"job": str(tmp_path / "job"), "title": "Nearly Safe"}
    finally:
        del app.destroy


def test_a_failed_update_while_reading_goes_home_where_resume_is(window, tmp_path, monkeypatch):
    win, app = window

    class Breaks(FakeLauncher):
        def update(self, arg=None):
            raise OSError("no internet")
    monkeypatch.setattr(app, "_launcher", lambda: Breaks())
    monkeypatch.setattr(win.messagebox, "askyesno", lambda *a, **k: True)
    errors = []
    monkeypatch.setattr(win.messagebox, "showerror", lambda *a, **k: errors.append(a[1]))
    app._new_page("Narrating the book…")
    app.maker = FakeMaker(tmp_path / "job")
    maker = app.maker
    app.check_updates()
    assert _until(app, lambda: errors)
    assert maker.stopped.is_set() and app.maker is None
    assert app.steps_page is not None                # back on the first page
    assert "press Resume" in errors[0]


def test_after_the_update_it_is_back_where_it_was(window, tmp_path, monkeypatch):
    win, app = window
    monkeypatch.setattr(win.engine, "cover_online", lambda book: None)
    ran = []
    monkeypatch.setattr(app, "run_job", lambda jobdir, title: ran.append((jobdir, title)))
    # the book being read: it carries on
    job = tmp_path / "job"
    job.mkdir()
    (job / "job.json").write_text("{}")
    app._carry_on({"job": str(job), "title": "Nearly Safe"})
    assert ran == [(job, "Nearly Safe")]
    # a finished one isn't read again
    (job / "done.json").write_text("{}")
    app._carry_on({"job": str(job), "title": "Nearly Safe"})
    assert len(ran) == 1
    # the book and step chosen
    book = make_epub(tmp_path / "book.epub", STORY)
    app._carry_on({"book": str(book), "step": 5, "series": "Grace Ford", "number": "2"})
    assert _until(app, lambda: app.book is not None, 15)
    _pump(app, 0.2)
    assert app.steps_page.now == 5
    assert (app.series_var.get(), app.number_var.get()) == ("Grace Ford", "2")
    assert app.book["title"] == "Nearly Safe"
