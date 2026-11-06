"""The graphics-card readers (readaloud_gpu): what can be tested without a graphics card.

The listen-back check, how a directed chapter becomes the units each voice reads, and the
reading loop with a stand-in voice and stand-in ears (read again when a word is doubled)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readaloud as R  # noqa: E402
import readaloud_gpu as G  # noqa: E402


def test_a_doubled_word_is_caught():
    # both from the first tests on the owner's laptop (Vermilion, chapter 1)
    s, why = G.check("I knew I must listen.", "I knew knew I must listen.")
    assert s and "doubled" in why
    s, why = G.check("As I listened, my memory seemed more real than what Rick was telling me.",
                     "As I listened, my memory seemed more real than what Rick was telling me. me.")
    assert s and "doubled" in why


def test_a_dropped_word_in_a_short_line_is_caught():
    s, why = G.check("I'm listening.", "Listening?")
    assert s and "dropped" in why


def test_small_differences_are_fine():
    assert G.check("my sister Sybil, my half sister, but from her husband",
                   "my sister Sybil, my half-sister, but from her husband")[0] == 0
    assert G.check("I'd both loved and resented him, more than ever", "I both loved and resented him, more than ever")[0] == 0
    # a respelled name heard as something else isn't a mistake
    assert G.check("She went to Tlaquepaque in the rain.", "She went to Lockapocky in the rain.",
                   skip={"tlaquepaque"})[0] == 0


def test_spelling_and_numbers_are_not_mistakes():
    # each of these had a good line read three times over (Vermilion, the first real test)
    assert G.check("Casinos and race tracks were small time to him", "Casinos and racetracks were small time to him")[0] == 0
    assert G.check('"Lindsay, are you all right?"', "Lindsey, are you all right?")[0] == 0
    assert G.check("when Sybil had been twenty-five, a stunningly successful model",
                   "when Sybil had been 25, a stunningly successful model")[0] == 0


def test_mostly_different_is_caught():
    assert G.check("The telephone call didn't come from my sister.", "Hello there, how are you today friend?")[0]


def directed_job(tmp_path, reader="acting", voice="grace", speed=1.0):
    jobdir = tmp_path / "job"
    jobdir.mkdir()
    chapters = [{"title": "One", "words": 20, "paras": [
        ["h", "Chapter One", {"x": "warm", "m": "plain"}],
        ["p", "She went to Tlaquepaque in the rain.", {"x": "calm", "m": "sad, slow", "s": 0.92, "g": 1.6}],
        ["p", '"Are you all right?"', {"x": "warm", "m": "gentle, worried", "v": "jack", "who": "rick", "g": 0.12}],
        ["b", ""],
        ["p", "It was over.", {"x": "strong"}]]}]
    (jobdir / "chapters.json").write_text(json.dumps(chapters), encoding="utf8")
    job = {"reader": reader, "voice": voice, "speed": speed, "bitrate": "64k",
           "respell": {"Tlaquepaque": "tlah-kuh-pah-kay"}, "manners": {"rick": "deep, steady"}}
    (jobdir / "job.json").write_text(json.dumps(job), encoding="utf8")
    return jobdir, chapters, job


def test_a_chapter_becomes_units_with_their_directions(tmp_path):
    _, chapters, job = directed_job(tmp_path)
    paras = G.chapter_units(chapters[0], job)
    assert [round(g, 2) for g, _ in paras] == [0.0, 1.6, 0.12, R.GAP_BREAK, 0.0]
    sad = paras[1][1][0]
    assert sad["text"] == "She went to tlah-kuh-pah-kay in the rain." and sad["orig"].startswith("She went to Tlaquepaque")
    assert sad["voice"] == "grace" and sad["note"] == "sad, slow" and sad["pace"] == "slower" and sad["feel"] == "calm"
    rick = paras[2][1][0]
    assert rick["voice"] == "jack" and rick["manner"] == "deep, steady"
    voice = type("V", (), {})()
    inst = G.Voice._instruct(voice, rick)
    assert inst.startswith(G.GPU_VOICES["jack"][1]) and "deep, steady" in inst and "gentle, worried" in inst
    assert "slower" in G.Voice._instruct(voice, sad)


def test_a_kokoro_voice_falls_back_to_the_default(tmp_path):
    _, chapters, job = directed_job(tmp_path, voice="af_heart")
    assert G.chapter_units(chapters[0], job)[1][1][0]["voice"] == G.DEFAULT_GPU_VOICE


class FakeVoice:
    sr = 24000
    batch = 4

    def __init__(self):
        self.calls = []

    def say(self, units):
        import numpy as np
        self.calls.append([u["text"] for u in units])
        return [0.3 * np.sin(np.arange(int(0.05 * self.sr * len(u["text"].split()))) / 5.0).astype("float32")
                for u in units]


class FakeEars:
    """Hears a doubled word the first time it hears "It was over."."""

    def __init__(self):
        self.n = 0

    def hear(self, x, sr):
        return None


def test_a_line_said_wrong_is_read_again():
    import numpy as np
    voice = FakeVoice()
    heard = iter(["It was was over.", "It was over."])

    class Ears:
        def hear(self, x, sr):
            return next(heard)
    log = []
    takes = G.say_checked(voice, Ears(), [{"text": "It was over."}], log.append)
    assert len(voice.calls) == 2 and len(takes) == 1 and len(takes[0])
    assert "doubled" in log[0]


def test_reading_a_chapter_with_a_stand_in_voice(tmp_path):
    if not shutil_which_ffmpeg():
        pytest.skip("needs ffmpeg")
    jobdir, chapters, job = directed_job(tmp_path, speed=1.1)
    done = []
    G.speak_chapter(FakeVoice(), FakeEars(), jobdir, 0, report=done.append)
    f = R.chapter_file(jobdir, 0)
    assert f.exists() and R.probe_duration(f) > 1.0
    assert done[-1] == sum(len(p[1].split()) for p in chapters[0]["paras"] if p[0] != "b")


def shutil_which_ffmpeg():
    try:
        R.tool("ffmpeg")
        return True
    except RuntimeError:
        return False


def test_every_voice_has_its_clip_and_ships():
    v = json.loads((Path(G.HERE) / "version.json").read_text(encoding="utf8"))
    for vid in G.GPU_VOICES:
        assert G.voice_clip(vid).exists(), vid
        assert G.voice_clip(vid).name in v["files"]
    for f in ("readaloud_gpu.py", "readaloud_gpu_req.txt"):
        assert f in v["files"]
    assert set(G.NARRATORS) <= set(G.GPU_VOICES)


def test_no_graphics_card_says_so(monkeypatch):
    def no_smi(*a, **k):
        raise OSError("not found")
    monkeypatch.setattr(G.subprocess, "run", no_smi)
    ok, why = G.gpu_check()
    assert not ok and "NVIDIA" in why and "Quick" in why
