"""Shared setup for the CleanListen tests.

Run from the repo folder:  python -m pytest
(needs numpy and pytest; the smoke test also needs ffmpeg, see test_smoke.py)
"""
import os
import sys
import tempfile
from pathlib import Path

# The engine modules read %LOCALAPPDATA%\CleanListen when they are imported (learned
# choices, settings, Claude findings). Point that at an empty temp folder first, so the
# tests never read or change the real app's data on this PC.
REAL_APPDATA = os.environ.get("LOCALAPPDATA", "")   # only used to find the installed ffmpeg
_APPDATA = tempfile.mkdtemp(prefix="cleanlisten-tests-")
os.environ["LOCALAPPDATA"] = _APPDATA
# The real inbox address is built in: point sending at a closed port so no test can ever
# send to it (tests that need an inbox set their own).
os.environ["CLEANLISTEN_INBOX"] = "http://127.0.0.1:9/exec"

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ---------------------------------------------------------------------------------------------
# Nothing pops up while the tests run (the owner, 2026-11-13, to every chat working on her PC:
# "can you keep everything from keep popping up while you are making changes? only fully pop when
# absolutely necessary"; as CleanView's tests/support.py):
# - every Tk window is drawn see-through (sizes are still measured, clicks sent by a test still
#   arrive, Windows still counts it as open);
# - message boxes answer quietly (OK, or "No" to a question) instead of waiting on the screen;
# - opening a file or folder (os.startfile, Explorer, Notepad) is noted, not done;
# - no sounds.
# A test that wants to see one of these sets its own stand-in, which wins. Code a test runs in
# another Python starts with HIDE so its windows are see-through too.
# ---------------------------------------------------------------------------------------------
HIDE = """
import tkinter as _tk_hide
def _see_through(cls):
    made = cls.__init__
    def init(self, *a, **k):
        made(self, *a, **k)
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
    cls.__init__ = init
_see_through(_tk_hide.Tk)
_see_through(_tk_hide.Toplevel)
"""
exec(HIDE)

import subprocess  # noqa: E402
import tkinter.messagebox as _boxes  # noqa: E402

BOXES = []          # (kind, title, message) of every box a test would have shown
OPENED = []         # files and folders a test would have opened


def _quiet_box(kind, answer):
    def box(title=None, message=None, **kw):
        BOXES.append((kind, title, message))
        return answer
    return box


for _kind, _answer in (("showinfo", "ok"), ("showwarning", "ok"), ("showerror", "ok"),
                       ("askyesno", False), ("askokcancel", False), ("askretrycancel", False),
                       ("askyesnocancel", None), ("askquestion", "no")):
    setattr(_boxes, _kind, _quiet_box(_kind, _answer))

if hasattr(os, "startfile"):
    os.startfile = lambda path, *a, **k: OPENED.append(str(path))

_POPUPS = ("explorer", "explorer.exe", "notepad", "notepad.exe")


def _pops_up(args):
    first = (args.strip().split() or [""])[0] if isinstance(args, str) else (
        str(args[0]) if args else "")
    return os.path.basename(first.strip('"')).lower() in _POPUPS


class _QuietPopen(subprocess.Popen):
    """A real Popen, except that Explorer and Notepad are noted and a do-nothing Python runs."""

    def __init__(self, args, *a, **k):
        if _pops_up(args):
            OPENED.append(args if isinstance(args, str) else " ".join(map(str, args)))
            args, k = [sys.executable, "-c", "pass"], {x: v for x, v in k.items() if x != "shell"}
        super().__init__(args, *a, **k)


subprocess.Popen = _QuietPopen
try:
    import winsound  # noqa: E402
    winsound.MessageBeep = lambda *a, **k: None
    winsound.PlaySound = lambda *a, **k: None
except ImportError:
    pass

import cleanlisten as E  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _own_ai_answers(tmp_path, monkeypatch):
    """CleanRead keeps the AI helper's answers per book; each test starts with none."""
    import cleanread
    monkeypatch.setattr(cleanread, "ANSWERS_DIR", tmp_path / "cleanread_ai_answers")


@pytest.fixture(autouse=True)
def _english_unless_the_test_says(monkeypatch):
    """The language being cleaned is one setting for the whole program (cvlang.LANG): each test
    starts and ends in English."""
    E.use_language("en")
    yield
    E.use_language("en")


def words(text):
    """Text -> the normalised word list the detectors work on."""
    return [w for w in (E.norm(t) for t in text.split()) if w]


def make_book(sentences, part=0, start=0.0, step=0.3):
    """A fake transcript: each word lasts `step` seconds, with a short pause between
    sentences. Returns (asr, sentence ranges) in the shapes analyze() produces."""
    asr, sents, t = [], [], start
    for s in sentences:
        a = len(asr)
        for w in s.split():
            asr.append({"t": w, "s": round(t, 3), "e": round(t + step - 0.05, 3),
                        "part": part, "n": E.norm(w)})
            t += step
        sents.append([a, len(asr) - 1])
        t += 0.5
    return asr, sents
