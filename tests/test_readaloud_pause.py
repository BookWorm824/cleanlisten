"""ReadAloud's Pause button (the owner, 2026-11-12: "should we have a pause button next to the
cancel button"): the reading programs, and what they started, freeze where they are until Resume."""
import importlib.util
import subprocess
import sys
import time

from conftest import REPO

import readaloud as R

# writes a line every 0.1 s, and starts a child that does the same (like a reader and its ffmpeg)
TICKER = r"""
import subprocess, sys, time
out = sys.argv[1]
if len(sys.argv) > 2:
    subprocess.Popen([sys.executable, __file__, sys.argv[2]])
while True:
    with open(out, "a") as f:
        f.write("x")
    time.sleep(0.1)
"""


def _size(p):
    return p.stat().st_size if p.exists() else 0


def _growing(*files, secs=0.8):
    before = [_size(f) for f in files]
    time.sleep(secs)
    return [_size(f) > b for f, b in zip(files, before)]


def test_pause_freezes_the_reader_and_what_it_started_and_resume_carries_on(tmp_path):
    script = tmp_path / "ticker.py"
    script.write_text(TICKER)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    p = subprocess.Popen([sys.executable, str(script), str(a), str(b)])
    m = R.Maker(tmp_path, workers=(1, 1))
    try:
        t = time.time()
        while not (_size(a) and _size(b)) and time.time() - t < 20:
            time.sleep(0.1)
        m.procs[0] = p
        assert _growing(a, b) == [True, True]
        m.pause()
        assert m.paused and len(m._frozen) >= 2          # the reader and its child
        time.sleep(0.3)
        assert _growing(a, b) == [False, False]
        m.resume()
        assert not m.paused and m._frozen == [] and R._FROZEN == {}
        assert _growing(a, b) == [True, True]
        # stopping while paused lets them go first: a frozen program can't stop
        m.pause()
        m.procs.clear()                                  # (so stop() doesn't wait 8 s for the ticker)
        m.stop()
        assert not m.paused and R._FROZEN == {}
        assert _growing(a, b) == [True, True]
    finally:
        R.thaw_all()
        for pid in R._process_tree(p.pid)[::-1]:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def test_paused_time_doesnt_count_towards_the_time_left(tmp_path):
    m = R.Maker(tmp_path, workers=(1, 1))
    c0 = m._clock()
    m.pause()
    time.sleep(0.5)
    assert m._clock() - c0 < 0.1
    m.resume()
    time.sleep(0.3)
    assert 0.2 < m._clock() - c0 < 0.5


def test_ollama_is_never_frozen():
    # other programs share it
    src = (REPO / "readaloud.py").read_text("utf8")
    tree = src[src.index("def _process_tree("):src.index("def _suspend(")]
    assert '"ollama" in names.get(c, "")' in tree


class _Lbl:
    def __init__(self, text=""):
        self.text = text

    def config(self, text=None, **_):
        if text is not None:
            self.text = text

    def cget(self, _):
        return self.text


class _Maker:
    paused = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


def test_the_pause_button_says_resume_and_the_status_says_paused():
    spec = importlib.util.spec_from_file_location("ReadAloudPause", REPO / "ReadAloud.pyw")
    win = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(win)
    app = win.App.__new__(win.App)
    app.maker, app.job, app.watch = _Maker(), 1, None
    app.pause_btn, app.status, app.left_lbl = _Lbl("Pause"), _Lbl("Reading…"), _Lbl("About 2 hours left")

    class _Bar(dict):
        def winfo_exists(self):
            return True
    app.pb = _Bar(value=0)
    app.toggle_pause()
    assert app.maker.paused and app.pause_btn.text == "Resume"
    assert app.status.text == "Paused — press Resume to carry on." and app.left_lbl.text == ""
    # the book's own messages don't cover up "Paused"
    app._handle(("for_job", 1, ("progress", 0.5, "Reading the book aloud… 3 of 9 chapters done", 3600)))
    assert app.status.text == "Paused — press Resume to carry on." and app.pb["value"] == 500
    app.toggle_pause()
    assert not app.maker.paused and app.pause_btn.text == "Pause"
    assert app.status.text == "Reading the book aloud… 3 of 9 chapters done"
    src = (REPO / "ReadAloud.pyw").read_text("utf8")
    run = src[src.index("    def run_job("):src.index("    def toggle_pause(")]
    assert 'text="Pause"' in run and 'text="Stop for now"' in run
