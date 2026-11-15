""""Send to phone": the book's original audio and the list CleanShelf (the Android app) follows, so a
phone plays it clean without a cleaned copy ever being saved (the owner, 2026-11-14, "go head and
start building something like that")."""
import hashlib
import json

import cleanlisten as E
from conftest import REPO


def book(tmp_path, monkeypatch, disc_folders=False):
    files = []
    for i in range(2):
        folder = tmp_path / "src" / (f"Disc {i + 1}" if disc_folders else "")
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / ("Track 01.mp3" if disc_folders else f"0{i + 1} Chapter.mp3")
        f.write_bytes(bytes([i]) * (1000 + i))
        files.append(str(f))
    work = tmp_path / "work"
    work.mkdir()
    st = {"parts": files, "title": "The Test Book", "language": "en",
          "mutes": [{"part": 0, "s": 10.0, "e": 10.4, "cat": "moderate", "word": "d***", "on": True},
                    {"part": 0, "s": 10.3, "e": 10.8, "cat": "mild", "on": True},      # overlaps
                    {"part": 0, "s": 20.0, "e": 20.5, "cat": "mild", "on": False},     # unticked
                    {"part": 1, "s": 5.0, "e": 5.5, "cat": "mine"}],                   # on by default
          "scenes": [{"part": 1, "s": 30.0, "e": 90.0, "kind": "violence", "cut": True,
                      "text": "He hit him over and over."},
                     {"part": 0, "s": 50.0, "e": 60.0, "kind": "ref", "cut": False}]}
    (work / "analysis.json").write_text(json.dumps(st))
    monkeypatch.setattr(E, "probe_duration", lambda p: 120.0)
    return work, files


def test_the_folder_has_the_originals_and_the_list(tmp_path, monkeypatch):
    work, files = book(tmp_path, monkeypatch)
    said = []
    out = E.send_to_phone(work, tmp_path / "phone", "The Test Book", "A. Writer", "Kids",
                          "Taking out: swearing.", "CleanListen 1.17.37",
                          progress=lambda f, m: said.append(m))
    assert out == tmp_path / "phone" / "The Test Book"
    names = sorted(p.name for p in out.iterdir())
    assert names == ["01 Chapter.mp3", "02 Chapter.mp3", "cleanshelf.json"]
    assert (out / "01 Chapter.mp3").read_bytes() == open(files[0], "rb").read()     # untouched
    lst = json.loads((out / "cleanshelf.json").read_text("utf8"))
    assert lst["format"] == "cleanshelf-list" and lst["version"] == 1 and lst["kind"] == "audiobook"
    assert (lst["title"], lst["author"], lst["profile"]) == ("The Test Book", "A. Writer", "Kids")
    assert lst["parts"][0] == {"file": "01 Chapter.mp3", "bytes": 1000, "seconds": 120.0,
                               "sha1": hashlib.sha1(bytes([0]) * 1000).hexdigest()}
    # only what's ticked, overlaps joined, the same times saving would use
    assert lst["mute"] == [{"part": 0, "from": 10.0, "to": 10.8, "why": "moderate"},
                           {"part": 1, "from": 5.0, "to": 5.5, "why": "mine"}]
    assert lst["skip"] == [{"part": 1, "from": 30.0, "to": 90.0, "why": "violence"}]
    # times only: never the book's words
    text = (out / "cleanshelf.json").read_text("utf8")
    assert "d***" not in text and "hit him" not in text
    assert said[-1] == "Ready for the phone." and not (tmp_path / "phone" / "The Test Book (getting ready)").exists()


def test_sent_again_it_replaces_the_folder(tmp_path, monkeypatch):
    work, _ = book(tmp_path, monkeypatch)
    out = E.send_to_phone(work, tmp_path / "phone", "The Test Book")
    (out / "old leftover.txt").write_text("x")
    out = E.send_to_phone(work, tmp_path / "phone", "The Test Book")
    assert not (out / "old leftover.txt").exists() and (out / "cleanshelf.json").exists()


def test_disc_folders_get_flat_names_that_dont_clash(tmp_path, monkeypatch):
    work, files = book(tmp_path, monkeypatch, disc_folders=True)
    assert E.phone_names(files) == ["Disc 1 - Track 01.mp3", "Disc 2 - Track 01.mp3"]
    assert E.phone_names(["a/x.mp3", "a/x.MP3"]) == ["x.mp3", "x (2).mp3"]
    assert E.phone_names(["a/cleanshelf.json"]) == ["cleanshelf (2).json"]
    out = E.send_to_phone(work, tmp_path / "phone", 'A: Bad/Name?')
    assert out.name == "A BadName"                             # a name Windows and the phone take


def test_the_review_page_offers_it():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    assert 'menu.add_command(label="Send to phone or tablet (CleanShelf)…", command=self.send_to_phone)' in src
    assert 'places["phone_dir"] = d' in src
