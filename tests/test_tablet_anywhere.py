"""To a tablet anywhere (the owner, 2026-11-20: her niece's tablet, wherever it is, and from any of her devices):
the book file goes to her always-on home computer with Tailscale's own "Send file" (`tailscale file cp`, only
her own devices), and CleanRead Mobile on the tablet fetches it from there. Tailscale itself is pretended here."""
import shutil
import subprocess
import types

import pytest

import cleanlisten as E
from conftest import REPO
from test_phone_ways import book, read_book_file  # noqa: F401  (the same pretend book)

TARGETS = ("100.80.155.28\teluktronic\toffline; last seen 27h48m0s ago\n"
           "100.67.202.36\tlaurens-s21\n100.66.214.124\tmsi-j\n100.73.211.119\tryzen\n")


def test_tailscales_list_of_devices_that_take_files():
    assert E.parse_tailscale_targets(TARGETS) == [
        {"name": "laurens-s21", "online": True}, {"name": "msi-j", "online": True},
        {"name": "ryzen", "online": True}, {"name": "eluktronic", "online": False}]
    assert E.parse_tailscale_targets("") == []


class FakeTailscale:
    """Answers like tailscale.exe: --targets lists devices; `file cp <file> ryzen:` keeps a copy of the file."""
    def __init__(self, tmp_path, code=0, said=b""):
        self.got, self.calls, self.code, self.said, self.tmp = [], [], code, said, tmp_path

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if args[1:] == ["file", "cp", "--targets"]:
            return types.SimpleNamespace(returncode=self.code, stdout=TARGETS.encode() if not self.code else b"",
                                         stderr=self.said)
        if args[1:3] == ["file", "cp"]:
            if not self.code:
                keep = self.tmp / "sent"
                keep.mkdir(exist_ok=True)
                self.got.append(shutil.copy(args[3], keep))
            return types.SimpleNamespace(returncode=self.code, stdout=b"", stderr=self.said)
        raise AssertionError(args)


def test_the_book_goes_to_the_home_computer_as_one_book_file(book, tmp_path, monkeypatch):
    work, files = book
    fake = FakeTailscale(tmp_path)
    monkeypatch.setattr(subprocess, "run", fake)
    said = []
    name = E.send_to_mailbox(work, "ryzen", "The Test Book", made_by="CleanListen test", exe="tailscale.exe",
                             progress=lambda f, m: said.append(m))
    assert name == "The Test Book.cleanshelf"
    assert fake.calls[-1][:3] == ["tailscale.exe", "file", "cp"] and fake.calls[-1][4] == "ryzen:"
    lst, parts = read_book_file(open(fake.got[0], "rb").read())
    assert lst["title"] == "The Test Book" and parts[0] == open(files[0], "rb").read()
    assert "Sending it to ryzen with Tailscale…" in said and said[-1] == "Sent."


@pytest.mark.parametrize("said, words", [
    (b"tailscale: target \"ryzen\" is offline", "ryzen isn't answering. Make sure it's switched on"),
    (b"unknown target; tailscale file cp --targets", "doesn't know a computer called ryzen"),
    (b"something else went wrong", "couldn't send the book to ryzen. (something else went wrong)"),
])
def test_when_it_cant_send_it_says_so_plainly(tmp_path, monkeypatch, said, words):
    monkeypatch.setattr(subprocess, "run", FakeTailscale(tmp_path, code=1, said=said))
    f = tmp_path / "Book.cleanshelf"
    f.write_bytes(b"x")
    with pytest.raises(RuntimeError, match=words.replace("(", r"\(").replace(")", r"\)")):
        E.send_by_tailscale(f, "ryzen", exe="tailscale.exe")


def test_tailscale_missing_or_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "tailscale_exe", lambda: None)
    with pytest.raises(RuntimeError, match="Tailscale isn't on this computer"):
        E.tailscale_devices()
    monkeypatch.setattr(subprocess, "run", FakeTailscale(tmp_path, code=1))
    with pytest.raises(RuntimeError, match="Tailscale isn't connected on this computer"):
        E.tailscale_devices(exe="tailscale.exe")
    monkeypatch.setattr(subprocess, "run", FakeTailscale(tmp_path))
    assert [d["name"] for d in E.tailscale_devices(exe="tailscale.exe")][:3] == ["laurens-s21", "msi-j", "ryzen"]


def test_the_window_offers_a_tablet_anywhere():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    for said in ('text="To a tablet anywhere"', "command=self._phone_anywhere)", "engine.send_to_mailbox(",
                 "engine.tailscale_devices()", 'places["mailbox"]', '"ryzen" if "ryzen" in names',
                 'elif kind == "phone_devices":'):
        assert said in src, said
