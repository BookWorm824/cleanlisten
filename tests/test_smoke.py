"""Smoke test: analyze() then render() on a short generated clip.

Listening (speech recognition) is skipped by handing analyze() a ready-made transcript.json,
the same file it saves after listening, so no speech model is needed. ffmpeg is needed: it is
found on PATH or in the installed app (%LOCALAPPDATA%\\CleanListen\\app\\bin); without it this
test is skipped.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import cleanlisten as E
from conftest import REAL_APPDATA

DUR = 14.0
# (start time, text) - one sentence per entry, each word 0.3 s long
SCRIPT = [
    (0.5, "It was a quiet morning in the village."),
    (3.5, "Damn it, he said, and slammed the door."),
    (7.0, "Later they talked about sex for an hour."),
    (11.0, "Then everyone went home."),
]


def _ffmpeg():
    if not shutil.which("ffmpeg"):
        app_bin = Path(REAL_APPDATA) / "CleanListen" / "app" / "bin"
        if (app_bin / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(app_bin) + os.pathsep + os.environ["PATH"]
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


pytestmark = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


def _pcm(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _rms(a, s, e, sr=16000):
    seg = a[int(s * sr):int(e * sr)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


@pytest.fixture
def clip(tmp_path):
    """A 14-second tone standing in for the narrator, and its transcript."""
    return _book(tmp_path, SCRIPT)


def _book(tmp_path, script):
    audio = tmp_path / "Book" / "Chapter One.wav"
    audio.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={DUR}",
                    "-ar", "16000", "-ac", "1", str(audio)], check=True)
    words = []
    for t, sentence in script:
        for w in sentence.split():
            words.append({"t": w, "s": round(t, 3), "e": round(t + 0.25, 3)})
            t += 0.3
    work = tmp_path / "job"
    work.mkdir()
    key = str(audio.resolve())
    (work / "transcript.json").write_text(json.dumps({key: words}))
    return audio, work, tmp_path / "Clean"


def test_analyze_then_render(clip):
    audio, work, out = clip

    st = E.analyze([audio], work, groups=("swearing", "mild", "deity", "sexual"),
                   find_sex=True, find_refs=True, log=lambda *a: None)

    # analyze: one muted word per list hit, the sex-talk sentence offered as a cut
    assert (work / "analysis.json").exists()
    assert len(st["sentences"]) == len(SCRIPT)
    muted = sorted((m["word_raw"], m["cat"]) for m in st["mutes"])
    assert muted == [("Damn", "mild"), ("sex", "sexual")]
    assert all(m["on"] for m in st["mutes"])
    assert [(sc["kind"], sc["text"]) for sc in st["scenes"]] == [("ref", SCRIPT[2][1])]
    assert st["scenes"][0]["cut"] is True
    damn = next(m for m in st["mutes"] if m["word_raw"] == "Damn")

    # render: the clean copy is shorter by the cut, the swear is silent, the rest isn't
    res = E.render(work, out, log=lambda *a: None)
    clean = out / "Chapter One.mp3"
    assert clean.exists()
    assert not list(out.glob("~saving~*"))
    assert res["cuts"] == 1 and res["mutes"] == 2

    cut = st["scenes"][0]
    cut_len = cut["e"] - cut["s"]
    assert E.probe_duration(clean) == pytest.approx(DUR - cut_len, abs=0.15)

    a = _pcm(clean)
    assert _rms(a, damn["s"] + 0.05, damn["e"] - 0.05) < 0.01     # muted (before the cut, so same time)
    assert _rms(a, 1.0, 3.0) > 0.05                               # untouched tone (RMS ~0.09) still there

    # the review screen's Play button: a WAV of the passage with a second either side
    wav = out / "preview.wav"
    a0, b0 = E.extract_clip(audio, cut["s"], cut["e"], wav)
    assert (a0, b0) == pytest.approx((cut["s"] - 1, cut["e"] + 1))
    assert E.probe_duration(wav) == pytest.approx(b0 - a0, abs=0.05)
    assert E.extract_clip(audio, 0.2, 0.5, wav)[0] == 0.0             # never before the start

    report = (out / "CleanListen report.txt").read_text(encoding="utf8")
    assert "2 words/phrases muted, 1 passages cut" in report
    assert "D***" in report and "Damn" not in report               # the report stars the words
    assert "sexual reference" in report


def test_strict_religion(tmp_path):
    """Strict religion cuts "thank God" and a verse; the normal setting leaves them."""
    audio, work, _ = _book(tmp_path, [
        (0.5, "We drove home in the rain."),
        (3.0, "Thank God you're safe, she said."),
        (6.0, "She prayed for her mother."),
        (8.5, "The Lord is my shepherd."),
    ])
    found = {}
    for strict in (False, True):
        st = E.analyze([audio], work, groups=(), find_sex=False, find_religion=True,
                       strict_religion=strict, log=lambda *a: None)
        found[strict] = [sc["text"] for sc in st["scenes"]]
        assert st["filters"]["strict_religion"] is strict
    assert found[False] == []
    assert found[True] == ["Thank God you're safe, she said.", "The Lord is my shepherd."]


def test_kid_topics(tmp_path):
    """Holidays, birthday candles and magic are cut only when ticked, and the report names them."""
    audio, work, _ = _book(tmp_path, [
        (0.5, "We drove home in the rain."),
        (3.0, "Santa left presents under the tree."),
        (6.0, "She blew out the candles on her cake."),
        (8.5, "The wizard waved his magic wand."),
    ])
    st = E.analyze([audio], work, groups=(), find_sex=False, log=lambda *a: None)
    assert st["scenes"] == []
    st = E.analyze([audio], work, groups=(), find_sex=False, find_topics=("holiday", "magic"),
                   log=lambda *a: None)
    assert [(sc["kind"], sc["text"]) for sc in st["scenes"]] == [
        ("holiday", "Santa left presents under the tree."),
        ("magic", "The wizard waved his magic wand.")]
    assert st["filters"]["kinds"] == ["holiday", "magic"]
