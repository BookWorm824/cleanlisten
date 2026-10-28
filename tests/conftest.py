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

import cleanlisten as E  # noqa: E402


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
