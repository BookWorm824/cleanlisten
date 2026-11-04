"""A cover from the internet when the book has none (Lauren, 2026-11-04: "anyway we can have
the cover picture an option for automatic?"). No real internet here: the searches and the
download are stand-ins."""
import json

import pytest

import cleanlisten as E
from test_m4b import has_cover, job, mp3_book, picture  # noqa: F401
from test_smoke import _ffmpeg

JPG = b"\xff\xd8\xff\xe0" + b"x" * 5000


def test_titles_are_compared_without_the_extras():
    assert E._title_key("At Home in Mitford: A Novel (Unabridged)") == "at home in mitford"
    assert E._title_key("The Clinic") == "clinic"
    assert E._title_key("Wings of a dream") == E._title_key("Wings of a Dream")


def test_only_the_same_book_counts():
    assert E.same_book("At Home in Mitford", "Jan Karon",
                       "At Home in Mitford: A Novel (Unabridged)", ["Jan Karon"])
    assert E.same_book("The Clinic", "Cate Quinn", "The Clinic", ["Cate Quinn", "Narrator"])
    # Apple Books' answers for "Nearly Safe Lisa Harris" (2026-11-04): none of them is the book
    for title, who in (("Lisa", "Lisa Curry"), ("The Unwanteds (Unabridged)", "Lisa McMann")):
        assert not E.same_book("Nearly Safe", "Lisa Harris", title, [who])
    assert not E.same_book("The Clinic", "Cate Quinn", "The Clinic", ["Someone Else"])
    assert not E.same_book("Mitford", "Jan Karon", "At Home in Mitford", ["Jan Karon"])
    assert E.same_book("The Clinic", "", "The Clinic", ["Anyone"])       # no author to check


@pytest.fixture
def web(monkeypatch):
    """Stand-in searches and downloads: {source: [(title, [authors], url)]}, {url: bytes}."""
    found, files, asked = {}, {}, []

    def source(name):
        def search(title, author):
            asked.append((name, title, author))
            if found.get(name) == "down":
                raise OSError("no internet")
            return iter(found.get(name, []))
        return name, search
    monkeypatch.setattr(E, "COVER_SOURCES", tuple(source(n) for n in
                                                  ("Audible", "Apple Books", "Open Library")))

    class Reply:
        def __init__(self, data):
            self.data = data

        def read(self, n=-1):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        if url not in files:
            raise OSError("404")
        return Reply(files[url])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return found, files, asked


def test_the_first_sure_match_is_saved_and_kept(tmp_path, web):
    found, files, asked = web
    found["Audible"] = [("Mitford", ["Jan Karon"], "https://a/wrong.jpg"),
                        ("At Home in Mitford", ["Jan Karon"], "https://a/right.jpg")]
    files["https://a/right.jpg"] = JPG
    res = E.find_cover_online("At Home in Mitford", "Jan Karon", tmp_path, log=lambda m: None)
    assert res["source"] == "Audible" and res["title"] == "At Home in Mitford"
    assert res["file"].endswith(".jpg") and open(res["file"], "rb").read() == JPG
    # asked once: the same book again comes from what was kept
    n = len(asked)
    assert E.find_cover_online("At Home in Mitford", "Jan Karon", tmp_path)["file"] == res["file"]
    assert len(asked) == n


def test_a_site_that_is_down_or_has_nothing_moves_on(tmp_path, web):
    found, files, asked = web
    found["Audible"] = "down"
    found["Apple Books"] = [("Wings of a Dream", ["Anne Mateer"], "https://b/blank.jpg")]
    files["https://b/blank.jpg"] = b"\xff\xd8\xff" + b"x" * 100          # Open Library's blank
    found["Open Library"] = [("Wings of a dream", ["Anne Mateer"], "https://c/cover.png")]
    files["https://c/cover.png"] = b"\x89PNG\r\n\x1a\n" + b"x" * 5000
    res = E.find_cover_online("Wings of a Dream", "Anne Mateer", tmp_path, log=lambda m: None)
    assert res["source"] == "Open Library" and res["file"].endswith(".png")


def test_nothing_sure_means_no_cover(tmp_path, web):
    found, files, asked = web
    found["Audible"] = [("Lisa", ["Lisa Curry"], "https://a/x.jpg")]
    files["https://a/x.jpg"] = JPG
    assert E.find_cover_online("Nearly Safe", "Lisa Harris", tmp_path, log=lambda m: None) is None
    assert E.find_cover_online("", "Lisa Harris", tmp_path) is None
    assert not list(tmp_path.glob("*.jpg"))


@pytest.mark.skipif(not _ffmpeg(), reason="ffmpeg isn't installed")
def test_saving_uses_the_cover_found_online(tmp_path, mp3_book, monkeypatch):
    parts, words = mp3_book
    for p in parts[0].parent.glob("*.*"):
        if p.suffix in (".jpg", ".png"):
            p.unlink()                                    # a book with no picture at all
    pic = picture(tmp_path / "from the web.jpg", "green")
    looked = []

    def online(title, author, folder, log=print):
        looked.append((title, author))
        return {"file": str(pic), "source": "Audible", "title": title, "author": author}
    monkeypatch.setattr(E, "find_cover_online", online)
    work = job(tmp_path, parts, words)
    res = E.render(work, tmp_path / "Clean", m4b=True, cover_online=True, log=lambda m: None)
    assert looked == [("The Clinic", "Cate Quinn")]
    assert has_cover(res["m4b"]["file"]) and res["m4b"]["cover_from"] == "Audible"
    assert "with the cover from Audible" in (tmp_path / "Clean" / "CleanListen report.txt").read_text()
    # off: not looked up
    looked.clear()
    work2 = tmp_path / "job2"
    work2.mkdir()
    for f in ("analysis.json", "transcript.json"):
        (work2 / f).write_text((work / f).read_text())
    res = E.render(work2, tmp_path / "Clean2", m4b=True, log=lambda m: None)
    assert looked == [] and not res["m4b"]["cover"]
