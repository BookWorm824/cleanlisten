"""A PNG cover in an M4B (Nearly Free, 2026-11-05: "Couldn't set the chapters of Molly Black -
Nearly Free.m4b: [ipod] Could not find tag for codec png"). An M4B takes only JPG covers, so
every cover is made a JPG. Needs ffmpeg."""
import pytest

import cleanlisten as E
from test_m4b import chapters, ff, has_cover, job, mp3_book, probe  # noqa: F401
from test_smoke import _ffmpeg

pytestmark = pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")


def png(path, color="blue"):
    ff("-f", "lavfi", "-i", f"color=c={color}:s=200x200", "-frames:v", "1", "-c:v", "png", path)
    return path


def cover_codec(path):
    return next(s["codec_name"] for s in probe(path)["streams"]
                if s.get("disposition", {}).get("attached_pic"))


@pytest.fixture
def png_m4b(tmp_path):
    """A 2-minute M4B whose own cover is a PNG (as an .m4a/.mp4 from some shops is)."""
    book = tmp_path / "Nearly Free"
    book.mkdir()
    pic = png(tmp_path / "cover.png")
    src = book / "Molly Black - Nearly Free.m4b"
    meta = tmp_path / "meta.txt"
    meta.write_text(";FFMETADATA1\ntitle=Nearly Free\nartist=Molly Black\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=60000\ntitle=One\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=60000\nEND=120000\ntitle=Two\n")
    ff("-f", "lavfi", "-i", "sine=f=440:d=120", "-i", pic, "-i", meta, "-map", "0:a", "-map", "1:v",
       "-c:a", "aac", "-b:a", "64k", "-c:v", "copy", "-disposition:v", "attached_pic",
       "-map_metadata", "2", "-map_chapters", "2", "-f", "mp4", src)
    assert cover_codec(src) == "png"
    return src


def test_a_png_cover_becomes_a_jpg(tmp_path):
    pic = png(tmp_path / "chosen.png")
    jpg = E.cover_file(str(pic), tmp_path)
    assert jpg.endswith(".jpg") and E.is_jpeg(jpg)
    assert E.cover_file(jpg, tmp_path) == jpg                     # a JPG stays as it is


def test_retagging_an_m4b_with_its_own_png_cover(tmp_path, png_m4b):
    E.retag_m4b(png_m4b, [(0, "Chapter 1"), (50, "Chapter 2")], workdir=tmp_path)
    assert [t for _, t in chapters(png_m4b)] == ["Chapter 1", "Chapter 2"]
    assert has_cover(png_m4b) and cover_codec(png_m4b) == "mjpeg"


def test_saving_the_nearly_free_way(tmp_path, png_m4b):
    """The clean copy of a one-file M4B with a PNG cover, given chapters and its cover."""
    work = job(tmp_path, [png_m4b])
    res = E.render(work, tmp_path / "Clean", cuts=[{"part": 0, "s": 10.0, "e": 20.0}], m4b=True,
                   log=lambda m: None)
    assert res["m4b"]["cover"] and cover_codec(res["m4b"]["file"]) == "mjpeg"


def test_a_png_cover_chosen_for_mp3_parts(tmp_path, mp3_book):
    parts, words = mp3_book
    work = job(tmp_path, parts, words)
    res = E.render(work, tmp_path / "Clean", m4b=True, cover=str(png(tmp_path / "mine.png", "red")),
                   log=lambda m: None)
    assert has_cover(res["m4b"]["file"]) and cover_codec(res["m4b"]["file"]) == "mjpeg"
