"""Every way to the phone or tablet (the owner, 2026-11-14: "lets do every way wifi bluetooth google
drive"): one .cleanshelf book file (Google Drive, Bluetooth, USB, email), and straight over Wi-Fi to a
tablet whose CleanShelf "Receive from PC" page is open. A pretend tablet here answers like the real
one (CleanShelf's FORMAT.md)."""
import hashlib
import http.server
import json
import socket
import threading

import pytest

import cleanlisten as E
from conftest import REPO


@pytest.fixture
def book(tmp_path, monkeypatch):
    files = []
    for i in range(2):
        f = tmp_path / "src" / f"0{i + 1} Chapter.mp3"
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(bytes([65 + i]) * (3_000_000 + i))          # big enough to come in pieces
        files.append(str(f))
    work = tmp_path / "work"
    work.mkdir()
    (work / "analysis.json").write_text(json.dumps({
        "parts": files, "title": "The Test Book",
        "mutes": [{"part": 0, "s": 1.0, "e": 1.5, "cat": "mild", "word": "d***"}],
        "scenes": [{"part": 1, "s": 10.0, "e": 20.0, "kind": "violence", "text": "He hit him."}]}))
    monkeypatch.setattr(E, "probe_duration", lambda p: 60.0)
    return work, files


def read_book_file(data):
    """What CleanShelf reads: the magic, the list's length, the list, then each part's bytes."""
    assert data[:12] == b"CLEANSHELF\x01\n"
    n = int.from_bytes(data[12:20], "big")
    lst = json.loads(data[20:20 + n].decode("utf8"))
    at, parts = 20 + n, []
    for p in lst["parts"]:
        parts.append(data[at:at + p["bytes"]])
        at += p["bytes"]
    assert at == len(data)                                   # nothing after the last part
    return lst, parts


def test_one_book_file_has_the_list_then_the_originals(book, tmp_path):
    work, files = book
    said = []
    out = E.save_phone_file(work, tmp_path / "out", "The Test Book", made_by="CleanListen test",
                            progress=lambda f, m: said.append((round(f, 2), m)))
    assert out.name == "The Test Book.cleanshelf" and not out.with_name(out.name + ".part").exists()
    lst, parts = read_book_file(out.read_bytes())
    assert lst["format"] == "cleanshelf-list" and lst["kind"] == "audiobook"
    assert [p["file"] for p in lst["parts"]] == ["01 Chapter.mp3", "02 Chapter.mp3"]
    for p, data, src in zip(lst["parts"], parts, files):
        assert data == open(src, "rb").read() and p["sha1"] == hashlib.sha1(data).hexdigest()
    assert lst["mute"] == [{"part": 0, "from": 1.0, "to": 1.5, "why": "mild"}]
    assert lst["skip"] == [{"part": 1, "from": 10.0, "to": 20.0, "why": "violence"}]
    assert b"d***" not in out.read_bytes() and b"He hit him" not in out.read_bytes()
    assert said[-1] == (1.0, "Saved.") and any("Saving the book file" in m for _, m in said)


class Tablet:
    """A pretend tablet with CleanShelf's "Receive from PC" page open."""

    def __init__(self, answer=(200, {"ok": True, "title": "The Test Book"})):
        self.got, self.headers, self.answer = [], [], answer
        tablet = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"])
                tablet.headers.append(dict(self.headers))
                tablet.got.append((self.path, self.rfile.read(n)))
                code, body = tablet.answer
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(0.2)
        self.udp_port = self.udp.getsockname()[1]
        self.running = True
        threading.Thread(target=self._answer_calls, daemon=True).start()

    def _answer_calls(self):
        while self.running:
            try:
                data, addr = self.udp.recvfrom(4096)
            except OSError:
                continue
            if json.loads(data).get("cleanshelf") == "find":
                self.udp.sendto(json.dumps({"cleanshelf": "here", "v": 1, "name": "Galaxy Tab A",
                                            "port": self.http.server_address[1]}).encode(), addr)

    def close(self):
        self.running = False
        self.http.shutdown()
        self.udp.close()


def test_over_wifi_the_tablet_is_found_and_gets_the_same_book(book, tmp_path):
    work, _ = book
    tablet = Tablet()
    try:
        phones = E.find_phones(timeout=1.0, port=tablet.udp_port, targets=["127.0.0.1"],
                               bind_host="127.0.0.1")          # (no firewall question on this PC)
        assert phones == [{"name": "Galaxy Tab A", "host": "127.0.0.1", "port": tablet.http.server_address[1]}]
        took = E.send_to_phone_wifi(work, phones[0], "The Test Book", made_by="CleanListen test")
        assert took == "The Test Book"
        (path, body), = tablet.got
        assert path == "/book" and tablet.headers[0]["X-CleanShelf"] == "1"
        # exactly what the book file holds
        same = E.save_phone_file(work, tmp_path / "out", "The Test Book", made_by="CleanListen test")
        assert body == same.read_bytes()
    finally:
        tablet.close()


def test_the_tablets_own_words_when_it_says_no(book):
    work, _ = book
    tablet = Tablet(answer=(400, {"ok": False, "problem": "There isn't room for this book on the tablet."}))
    try:
        phone = {"name": "Galaxy Tab A", "host": "127.0.0.1", "port": tablet.http.server_address[1]}
        with pytest.raises(RuntimeError, match="There isn't room"):
            E.send_to_phone_wifi(work, phone, "The Test Book")
    finally:
        tablet.close()


def test_nobody_answering_is_just_an_empty_list():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))                     # a port where nothing answers
    port = s.getsockname()[1]
    s.close()
    assert E.find_phones(timeout=0.6, port=port, targets=["127.0.0.1"], bind_host="127.0.0.1") == []


def test_a_tablet_that_stops_answering_is_said_plainly(book):
    work, _ = book
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                    # nothing there any more
    with pytest.raises(RuntimeError, match="stopped answering"):
        E.send_to_phone_wifi(work, {"name": "Tab", "host": "127.0.0.1", "port": port}, timeout=3)


def test_the_window_offers_every_way():
    src = (REPO / "CleanListen.pyw").read_text(encoding="utf8")
    for said in ('"Send to phone or tablet (CleanShelf)…"', '("Over Wi-Fi", ', '("Save a book file", ',
                 '"Send it by Bluetooth…"',
                 'subprocess.Popen(["fsquirt.exe"])', "engine.find_phones()",
                 "engine.send_to_phone_wifi(", "engine.save_phone_file("):
        assert said in src, said
