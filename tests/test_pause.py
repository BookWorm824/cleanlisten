"""Pause beside Cancel (the owner, 2026-11-12, via CleanView 1.18.66: "should we have a pause buton
next to the cancel button when a check is happening", then "yes build it"). CleanListen freezes a
book's worker and what it started (never Ollama, which other programs share); CleanRead's check waits
at its next step. Cancel, Remove and closing resume first, and the stuck-save watch doesn't count
paused time."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import bookqueue as BQ
import cleanlisten as E

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


class Proc:
    def __init__(self, pid=100):
        self.pid, self.stop_file = pid, Path(os.devnull)

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def workers(tree):
    calls = []
    w = BQ.Workers(lambda k, m: None, freeze=lambda pid, on: calls.append((pid, on)) or True,
                   tree=lambda pid: tree)
    w.procs["b"] = Proc()
    return w, calls


def test_pause_freezes_the_book_and_what_it_started_but_not_ollama():
    w, calls = workers([(100, "CleanListen.exe"), (101, "ffmpeg.exe"), (102, "ollama.exe"),
                        (103, "ollama_llama_server.exe")])
    assert w.pause("b") and w.paused("b")
    assert calls == [(100, True), (101, True)]
    w.resume("b")
    assert calls[2:] == [(101, False), (100, False)] and not w.paused("b")     # in reverse


def test_cancel_and_closing_resume_first(monkeypatch):
    monkeypatch.setattr(BQ, "kill_tree", lambda proc: None)     # never a real process
    w, calls = workers([(100, "python.exe")])
    w.pause("b")
    w.stop("b", wait=0.01)
    assert calls[-1] == (100, False) and not w.paused("b")
    w.pause("b")
    w.stop_all(wait=0.01)
    assert (100, False) in calls[3:] and not w.frozen


def test_nothing_to_pause_once_it_ended():
    w, calls = workers([(100, "python.exe")])
    w.procs["b"].poll = lambda: 0
    assert not w.pause("b") and not calls


@pytest.mark.skipif(not WINDOWS, reason="Windows processes")
def test_a_real_worker_really_stops_working_while_paused(tmp_path):
    out = tmp_path / "count.txt"
    code = (f"import time\nn = 0\nwhile True:\n    n += 1\n    open({str(out)!r}, 'w').write(str(n))\n"
            "    time.sleep(0.05)\n")
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        w = BQ.Workers(lambda k, m: None)
        proc.stop_file = tmp_path / "stop"
        w.procs["b"] = proc
        time.sleep(1.0)
        assert w.pause("b")
        time.sleep(0.3)
        frozen_at = out.read_text()
        time.sleep(1.0)
        assert out.read_text() == frozen_at          # nothing happened while paused
        w.resume("b")
        time.sleep(1.0)
        assert int(out.read_text()) > int(frozen_at)  # and it carried on
    finally:
        w.resume_all()
        proc.kill()
        proc.wait()


def test_the_stuck_save_watch_doesnt_count_paused_time(monkeypatch, tmp_path):
    # ffmpeg (and this process) were frozen for 40 minutes: not stuck
    clock = iter([0.0, 2.0, 2402.0, 2404.0, 2406.0])
    monkeypatch.setattr(E.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    sizes = iter([1, 2, 2, 3, 4])
    monkeypatch.setattr(E.os.path, "getsize", lambda p: next(sizes))
    polls = iter([None, None, None, None, 0])
    fake = types.SimpleNamespace(poll=lambda: next(polls), returncode=0, kill=lambda: None, wait=lambda: 0)
    monkeypatch.setattr(E, "popen", lambda cmd, **kw: fake)
    r = E.run_watched(["ffmpeg"], tmp_path / "x", stall=600, every=2.0)
    assert r.returncode == 0


def test_cleanlisten_rows_have_pause_beside_cancel():
    src = (ROOT / "CleanListen.pyw").read_text(encoding="utf8")
    assert 'text="Resume" if paused else "Pause"' in src and "def _pause_book" in src
    assert "Paused \\u2014 press Resume to carry on." in src


@pytest.fixture
def cr():
    return load("cr_pause_ui", "CleanRead.pyw")


def test_cleanread_check_waits_while_paused_and_carries_on(cr):
    app = types.SimpleNamespace(job=1, paused=True)
    asked = []
    t = threading.Thread(target=lambda: asked.append(cr.App._stop_or_wait(app, 1)))
    t.start()
    time.sleep(0.6)
    assert t.is_alive() and not asked            # waiting while paused
    app.paused = False
    t.join(2)
    assert asked == [False]                      # carries on, not cancelled


def test_cleanread_cancel_while_paused_stops_it(cr):
    app = types.SimpleNamespace(job=1, paused=True)
    asked = []
    t = threading.Thread(target=lambda: asked.append(cr.App._stop_or_wait(app, 1)))
    t.start()
    time.sleep(0.3)
    app.shown = []
    app.show_setup = lambda: app.shown.append("start page")
    cr.App.cancel(app)
    t.join(2)
    assert asked == [True] and app.paused is False and app.shown == ["start page"]


def test_cleanread_progress_doesnt_hide_paused(cr):
    class Lbl:
        def __init__(self):
            self.text = ""

        def config(self, text):
            self.text = text

        def winfo_exists(self):
            return True
    class PB(dict):
        def winfo_exists(self):
            return True
    app = types.SimpleNamespace(job=1, paused=True, pb=PB(value=0), status=Lbl())
    app.status.text = "Paused — press Resume to carry on."
    cr.App._handle(app, ("progress", 0.5, "AI is reading the book · 50%"))
    assert app.status.text.startswith("Paused") and app.pb["value"] == 500
    app.pause_btn = types.SimpleNamespace(winfo_exists=lambda: True, config=lambda **k: None)
    cr.App.toggle_pause(app)
    assert app.status.text == "AI is reading the book · 50%"
