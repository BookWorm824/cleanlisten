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


def _odd_m4b(tmp_path, attached):
    """A 2-minute M4B with a PNG picture and a JPG one; attached: their "cover" marks."""
    pic, jpg = png(tmp_path / "a.png"), tmp_path / "b.jpg"
    ff("-f", "lavfi", "-i", "color=c=red:s=200x200", "-frames:v", "1", jpg)
    src = tmp_path / "Book" / "Molly Black - Nearly Free.m4b"
    src.parent.mkdir(exist_ok=True)
    ff("-f", "lavfi", "-i", "sine=f=440:d=120", "-i", pic, "-i", jpg, "-map", "0:a", "-map", "1:v",
       "-map", "2:v", "-c:a", "aac", "-b:a", "64k", "-c:v", "copy",
       "-disposition:v:0", "attached_pic" if attached[0] else "0",
       "-disposition:v:1", "attached_pic" if attached[1] else "0", "-f", "mp4", src)
    return src


def covers(path):
    return [(s["codec_name"], s.get("disposition", {}).get("attached_pic"))
            for s in probe(path)["streams"] if s["codec_type"] == "video"]


@pytest.mark.parametrize("attached", [(True, False), (False, False), (True, True)])
def test_a_png_cover_with_another_picture(tmp_path, attached):
    # (True, False) is Nearly Free on 1.15.4: "codec not currently supported in container"
    src = _odd_m4b(tmp_path, attached)
    E.retag_m4b(src, [(0, "Chapter 1"), (60, "Chapter 2")], workdir=tmp_path)
    assert covers(src) == [("mjpeg", 1)]                       # one cover, a JPG
    assert [t for _, t in chapters(src)] == ["Chapter 1", "Chapter 2"]
    assert not list(tmp_path.glob("~*"))


def test_saving_a_book_with_a_png_cover_and_another_picture(tmp_path):
    src = _odd_m4b(tmp_path, (True, False))
    work = job(tmp_path, [src])
    res = E.render(work, tmp_path / "Clean", cuts=[{"part": 0, "s": 10.0, "e": 20.0}], m4b=True,
                   log=lambda m: None)
    assert covers(res["m4b"]["file"]) == [("mjpeg", 1)]


def test_the_error_shows_ffmpegs_reason_first():
    err = ("[ipod @ 0x1] Could not find tag for codec mjpeg in stream #2, codec not currently "
           "supported in container\n[out#0/ipod] Could not write header\n[vf#0:2] Error sending "
           "frames\n[vf#0:2] Task finished with error\n[out#0/ipod] Nothing was written")
    assert E.ffmpeg_says(err).startswith("[ipod @ 0x1] Could not find tag for codec mjpeg")
