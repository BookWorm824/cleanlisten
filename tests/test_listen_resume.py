"""Carrying on inside a file: a book that is one long file, stopped part-way (Cancel, closing
the window, an update), carries on from where it got to instead of listening from the start.

A stand-in recognizer gives words at fixed times in each 30 s chunk, so a run that was stopped
and carried on must give exactly the same words as one that went straight through. ffmpeg is
needed (found as in test_smoke.py); no speech model.
"""
import json
from types import SimpleNamespace

import pytest

import cleanlisten as E
from test_smoke import _ffmpeg

pytestmark = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


class FakeRec:
    """A word every second of each chunk; its text says where in the chunk it was."""

    def __init__(self):
        self.chunks = 0

    def create_stream(self):
        return SimpleNamespace(accept_waveform=self._accept, result=None)

    def _accept(self, sr, seg):
        self._len = len(seg) / sr

    def decode_stream(self, s):
        self.chunks += 1
        ts = [t + 0.25 for t in range(int(self._len))]
        s.result = SimpleNamespace(tokens=[f" w{t:.2f}" for t in ts], timestamps=ts,
                                   durations=[0.3] * len(ts))


@pytest.fixture
def long_file(tmp_path):
    import subprocess
    path = tmp_path / "Book" / "Whole Book.mp3"
    path.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=400",
                    "-ac", "1", "-b:a", "64k", str(path)], check=True)
    return path


def test_stopped_part_way_then_carried_on_hears_the_same(long_file):
    whole = E.transcribe(long_file, FakeRec())
    assert whole and whole[-1]["s"] > 390

    saved = []
    seen = []

    def stop_late():
        return bool(seen) and seen[-1] > 250

    with pytest.raises(KeyboardInterrupt):
        E.transcribe(long_file, FakeRec(), progress=seen.append, cancel=stop_late,
                     keep=lambda words, nxt: saved.append((list(words), nxt)), keep_every=60)
    words, nxt = saved[-1]
    assert 250 <= nxt < 300                      # kept when it was stopped, not 4 minutes back
    assert [n for _, n in saved[:-1]] == [84.0, 168.0]   # and at chunk edges a minute+ apart
    assert all(w["s"] < nxt + 1 for w in words)  # (chunks overlap: the next one's words start at +1 s)

    rec = FakeRec()
    rest = E.transcribe(long_file, rec, start=nxt, heard=words)
    assert rest == whole                         # exactly what a straight run hears
    assert rec.chunks < 7                        # only the end was listened to again


def test_analyze_carries_on_with_the_file_it_was_in(long_file, tmp_path, monkeypatch):
    monkeypatch.setattr(E, "load_recognizer", lambda *a, **k: FakeRec())
    work = tmp_path / "job"
    msgs = []

    def say(f, m):
        msgs.append((f, m))

    stop = {"at": 0.4}
    with pytest.raises(KeyboardInterrupt):
        E.analyze([long_file], work, progress=say, log=lambda m: None,
                  cancel=lambda: bool(msgs) and msgs[-1][0] > 0.92 * stop["at"])
    part_way = json.loads((work / "listening.json").read_text())
    assert part_way["part"] == str(long_file.resolve()) and part_way["next"] > 100
    assert not (work / "transcript.json").exists() or str(long_file.resolve()) not in json.loads(
        (work / "transcript.json").read_text())

    logs = []
    E.analyze([long_file], work, log=logs.append)
    assert any("Carrying on with Whole Book.mp3" in m for m in logs)
    assert not (work / "listening.json").exists()          # done with: gone
    got = json.loads((work / "transcript.json").read_text())[str(long_file.resolve())]
    assert got == E.transcribe(long_file, FakeRec())
