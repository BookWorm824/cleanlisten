"""A chapter with more than 100 mutes or cuts (CleanView 1.18.26, Jason's Shawshank Redemption):
ffmpeg can't read a sum of more than 100 between() terms and says "Error initializing filters ...
Cannot allocate memory", which also read as "This computer ran out of memory"."""
import json
import subprocess

import pytest

import bookqueue as Q
import cleanlisten as E
from test_smoke import _ffmpeg, _pcm, _rms

LONG = 400.0


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    if not _ffmpeg():
        pytest.skip("ffmpeg isn't installed")
    d = tmp_path_factory.mktemp("many")
    src = d / "Chapter 1.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=440:d={LONG}",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(src)], check=True)
    return src


def _work(tmp_path, src, mutes=()):
    work = tmp_path / "work"
    work.mkdir()
    (work / "analysis.json").write_text(json.dumps(
        {"parts": [str(src)], "scenes": [], "mutes": [dict(m, part=0) for m in mutes]}))
    return work


def _out(res):
    from pathlib import Path
    return next(Path(res["out"]).glob("*.mp3"))


@pytest.mark.parametrize("n,gap", [(150, 2.0), (1200, 0.3)])
def test_many_mutes_are_all_silent(tmp_path, book, n, gap):
    mutes = [{"part": 0, "s": 1 + i * gap, "e": 1 + i * gap + gap / 3, "src": "audio", "word": "damn"}
             for i in range(n)]
    res = E.render(_work(tmp_path, book), tmp_path / "Clean", mutes=mutes, log=lambda m: None)
    a = _pcm(_out(res))
    loud = _rms(a, 0.1, 0.9)
    assert loud > 0.03                    # ffmpeg's test tone is at 1/8 volume
    for m in (mutes[0], mutes[99], mutes[100], mutes[n // 2], mutes[-1]):
        mid = (m["s"] + m["e"]) / 2
        assert _rms(a, mid - 0.02, mid + 0.02) < loud * 0.05, m
        after = m["e"] + gap / 3          # between this mute and the next: the sound is kept
        assert _rms(a, after - 0.02, after + 0.02) > loud * 0.5, m


def test_many_cuts_are_all_taken_out(tmp_path, book):
    cuts = [{"part": 0, "s": 1 + i * 2.0, "e": 1.5 + i * 2.0} for i in range(120)]
    res = E.render(_work(tmp_path, book), tmp_path / "Clean", cuts=cuts, mutes=[], log=lambda m: None)
    assert abs(E.probe_duration(_out(res)) - (LONG - 60)) < 1.0


def test_one_filter_for_each_50_with_no_brackets():
    # Scarlet (Unabridged), one 7-hour MP3, didn't save on the owner's PC with 500 to a filter
    # bracketed in 50s (2026-11-11); 50 plain terms to a filter reads in any ffmpeg
    rs = [(i, i + 0.5) for i in range(1201)]
    f = E._range_filters(rs, rs[:120])
    mutes = [x for x in f if x.startswith("volume=")]
    cuts = [x for x in f if x.startswith("aselect=")]
    assert len(mutes) == 25 and len(cuts) == 3 and f[-1] == "asetpts=N/SR/TB"
    assert all(x.count("between(") <= 50 and ")+(" not in x and "((" not in x for x in mutes + cuts)
    assert E._ranges(rs[:3]) == "between(t,0.000,0.500)+between(t,1.000,1.500)+between(t,2.000,2.500)"
    assert E._range_filters([], []) == []


def test_a_seven_hour_book_with_thousands_of_mutes_and_cuts_saves(tmp_path):
    if not _ffmpeg():
        pytest.skip("ffmpeg isn't installed")
    src = tmp_path / "Scarlet (Unabridged).mp3"     # quiet, so a 7-hour file is quick to make
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                    "-t", "25000", "-c:a", "libmp3lame", "-b:a", "8k", str(src)], check=True)
    mutes = [{"part": 0, "s": 5 + i * 9.0, "e": 5.4 + i * 9.0, "src": "audio", "word": "damn"}
             for i in range(2700)]
    cuts = [{"part": 0, "s": 7 + i * 400.0, "e": 9 + i * 400.0} for i in range(60)]
    res = E.render(_work(tmp_path, src), tmp_path / "Clean", cuts=cuts, mutes=mutes, log=lambda m: None)
    assert abs(E.probe_duration(_out(res)) - (25000 - 120)) < 2.0


def test_the_error_shows_what_went_wrong_not_just_times():
    err = ("[Parsed_volume_3 @ 0000] Error when evaluating the expression '" +
           "+".join(f"between(t,{i}.320,{i}.510)" for i in range(23000, 23050)) +
           "' for enable\n[AVFilterGraph @ 0000] Error initializing filters\n"
           "Error opening output file F:\\Audiobooks\\Clean\\~saving~ Scarlet (Unabridged).mp3.")
    short = E._short_error(err)[-600:]
    assert "Error when evaluating the expression" in short and "for enable" in short
    assert "Error opening output file F:" in short and len(E._short_error(err)) < 500


def test_a_filter_ffmpeg_cant_read_isnt_called_out_of_memory():
    err = ("[Parsed_volume_0] Error when evaluating the expression '...between(t,8189.770,8191.030)' "
           "for enable\nError initializing filters\nError opening output files: Cannot allocate memory")
    assert Q.plain_error(err) == err
    assert Q.plain_error("bad allocation") == Q.OUT_OF_MEMORY
