"""Saving never finished (2026-11-05, "cleanListen has been stuck on my computer all day ...
stuck on save"): ffmpeg's AAC encoder in its default mode looped forever on two seconds of
Vermilion (mono, 24 kHz). CleanListen uses its fast mode, and stops a save that stops making
progress instead of waiting forever."""
import os
import sys
import time

import pytest

import cleanlisten as E
from test_smoke import _ffmpeg

VERMILION = r"C:\Users\morga\Downloads\Vermilion.m4b"     # (only on the owner's PC)


def test_aac_is_always_the_fast_mode():
    assert E.AAC == ["-c:a", "aac", "-aac_coder", "fast"]


def test_a_job_that_writes_nothing_is_stopped(tmp_path):
    # a stand-in for the stuck ffmpeg: running, writing nothing
    out = tmp_path / "out.m4b"
    out.write_bytes(b"x" * 67)
    t = time.time()
    r = E.run_watched([sys.executable, "-c", "import time; time.sleep(60)"], out, stall=3, every=0.5)
    assert r.returncode == -9 and "stopped making progress" in r.stderr
    assert time.time() - t < 30


def test_a_job_that_keeps_writing_is_left_alone(tmp_path):
    out = tmp_path / "out.bin"
    code = ("import time, sys\nf = open(sys.argv[1], 'wb')\nfor i in range(8):\n"
            "    f.write(b'x' * 100); f.flush(); time.sleep(0.5)\n")
    r = E.run_watched([sys.executable, "-c", code, str(out)], out, stall=2, every=0.25)
    assert r.returncode == 0 and os.path.getsize(out) == 800


@pytest.mark.skipif(not (_ffmpeg() and os.path.exists(VERMILION)), reason="the owner's book")
def test_vermilions_first_seconds_encode(tmp_path):
    out = tmp_path / "v.m4b"
    r = E.run_watched([E._tool("ffmpeg"), "-y", "-v", "error", "-t", "5", "-i", VERMILION,
                       "-map", "0:a", *E.AAC, "-b:a", "59861", str(out)], out, stall=60)
    assert r.returncode == 0 and abs(E.probe_duration(out) - 5) < 0.2
