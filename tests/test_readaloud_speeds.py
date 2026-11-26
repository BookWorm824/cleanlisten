"""ReadAloud remembers how fast this computer really makes a book with each voice, and its times
come from that (the owner, 2026-11-26: Truth Be Told with the acting voice on her laptop said 12
hours and took over 30; with Qwen steady it said "working out how long it will take" for 20
minutes, then 28 hours)."""
import json
import os
import threading
import time
from pathlib import Path

import pytest

import readaloud as R


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "JOBS", tmp_path / "readaloud")
    monkeypatch.setattr(R, "SPEEDS_FILE", tmp_path / "readaloud_speeds.json")
    return tmp_path


def make_job(home, key, reader, words, finished):
    """A book folder with chapters finished at these times (seconds ago -> chapter)."""
    d = home / "readaloud" / key
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"title": "T", "reader": reader}), encoding="utf8")
    (d / "chapters.json").write_text(json.dumps([{"title": str(i), "paras": [], "words": w}
                                                 for i, w in enumerate(words)]), encoding="utf8")
    now = time.time()
    for ago, i in finished:
        f = R.chapter_file(d, i)
        f.write_bytes(b"x")
        os.utime(f, (now - ago, now - ago))
    return d


def test_nothing_known_is_the_old_guess(home):
    for r in ("kokoro", "acting", "steady", "chatterbox"):
        wps, measured = R.making_speed(r)
        assert not measured and wps == pytest.approx(R.default_wps(r))
    hrs, _ = R.make_hours(94325, "acting")
    assert 11 < hrs < 13                      # what it said at midnight


def test_learns_from_a_book_made_before(home):
    # her laptop: acting, a chapter finished about every 75 minutes
    words = [2000] * 42
    ago = [10 * 3600 - k * 75 * 60 for k in range(7)]
    make_job(home, "laptop", "acting", words, list(zip(ago, [5, 26, 12, 16, 3, 20, 30])))
    R.learn_from_old_books()
    wps, measured = R.making_speed("acting")
    assert measured
    assert wps == pytest.approx(6 * 2000 / (6 * 75 * 60), rel=0.01)   # the first one isn't counted
    hrs, _ = R.make_hours(94325, "acting")
    assert hrs > 25


def test_a_long_stop_between_chapters_isnt_counted(home):
    words = [1000] * 6
    # two chapters, then stopped for 10 hours, then two more
    make_job(home, "b", "kokoro", words, [(14 * 3600, 0), (14 * 3600 - 600, 1),
                                         (3 * 3600 - 0, 2), (3 * 3600 - 600, 3)])
    R.learn_from_old_books()
    b = R.load_speeds()["books"]["b"]
    assert b["words"] == 2000 and b["secs"] == pytest.approx(1200, abs=2)


def test_one_measured_graphics_voice_corrects_the_others(home):
    R.remember_speed("x", "acting", R.default_wps("acting") * 3600 / 3, 3600)   # a third as fast
    steady, measured = R.making_speed("steady")
    assert not measured
    assert steady == pytest.approx(R.default_wps("steady") / 3, rel=0.01)
    assert R.making_speed("kokoro")[0] == pytest.approx(R.default_wps("kokoro"))   # not the graphics card


def test_measured_while_reading_beats_file_times(home):
    R.remember_speed("k", "acting", 1000, 1000, source="live")
    R.remember_speed("k", "acting", 5, 1000, source="files")
    assert R.load_speeds()["books"]["k"]["words"] == 1000
    assert R.speed_of_book("k") == (1000, 1000.0)


def test_only_the_newest_books_count(home):
    for k in range(R.SPEED_BOOKS):
        R.remember_speed(f"new{k}", "acting", 2000, 1000)
    d = R.load_speeds()
    d["books"]["old"] = {"reader": "acting", "words": 1, "secs": 100000, "source": "live", "when": "2000-01-01 00:00"}
    R._save_speeds(d)
    assert R.making_speed("acting")[0] == pytest.approx(2.0)


def test_time_left_shows_at_once_as_a_first_guess(home, monkeypatch):
    """No more 'Working out how long it will take' for half an hour: a guess as soon as the
    reading starts, and it says so."""
    d = make_job(home, "job", "kokoro", [500, 500, 500], [])
    monkeypatch.setattr(R, "have_model", lambda: True)
    seen = []
    m = R.Maker(d, lambda f, msg, left=None: seen.append((msg, left, m.left_guess)), workers=(1, 1))

    def one(i, partial, lock):
        for w in range(0, 501, 100):
            with lock:
                partial[i] = w
            time.sleep(0.3)
        R.chapter_file(d, i).write_bytes(b"x")
    monkeypatch.setattr(m, "_one", one)
    monkeypatch.setattr(R, "assemble", lambda *a, **k: {"done": True})
    m.run()
    reading = [s for s in seen if s[0].startswith("Reading the book aloud")]
    assert reading and reading[0][1] is not None and reading[0][2] is True
    assert reading[0][1] == pytest.approx(1500 / R.default_wps("kokoro"), rel=0.2)


def test_asleep_isnt_reading_time(home, monkeypatch):
    """The loop notices a jump in the clock (the computer slept) and leaves it out."""
    d = make_job(home, "job2", "kokoro", [300], [])
    monkeypatch.setattr(R, "have_model", lambda: True)
    m = R.Maker(d, lambda *a, **k: None, workers=(1, 1))
    real = time.time
    jump = {"at": None}

    def fake_time():
        t = real()
        if jump["at"] and t >= jump["at"]:
            return t + 3600          # an hour asleep
        return t

    def one(i, partial, lock):
        jump["at"] = real() + 1.2
        time.sleep(2.5)
        R.chapter_file(d, i).write_bytes(b"x")
    monkeypatch.setattr(m, "_one", one)
    monkeypatch.setattr(R, "assemble", lambda *a, **k: {})
    monkeypatch.setattr(R.time, "time", fake_time)
    m.run()
    assert m._paused_for > 3500
