"""Sending an exported file to the owner's inbox (cleanlisten_learn.send), against a
local stand-in for the Google Apps Script web app. Nothing goes to Google."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import cleanlisten_learn as learn


@pytest.fixture
def inbox(monkeypatch):
    """A local inbox. Like Google's, a POST is answered with a 302 to a page that
    gives the script's answer; set got["answer"] to change what it says."""
    got = {"posts": [], "answer": {"ok": True, "why": ""}}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got["posts"].append((self.headers["Content-Type"], json.loads(body)))
            self.send_response(302)
            self.send_header("Location", "/echo")
            self.end_headers()

        def do_GET(self):
            out = json.dumps(got["answer"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("CLEANLISTEN_INBOX", f"http://127.0.0.1:{srv.server_port}/exec")
    yield got
    srv.shutdown()
    srv.server_close()


def exported(tmp_path, name="CleanListen learned 2026-10-28.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"what": "CleanListen learned", "learned": {"cut": ["a line"]}}),
                    encoding="utf8")
    return path


def test_sends_the_file(inbox, tmp_path):
    path = exported(tmp_path)
    learn.send(path, "learned")
    ctype, body = inbox["posts"][0]
    assert ctype == "application/json"
    assert body == {"app": "CleanListen", "kind": "learned", "name": path.name,
                    "data": {"what": "CleanListen learned", "learned": {"cut": ["a line"]}}}


def test_inbox_says_no(inbox, tmp_path):
    inbox["answer"] = {"ok": False, "why": "empty or too big"}
    with pytest.raises(RuntimeError, match="empty or too big"):
        learn.send(exported(tmp_path), "refined")


def test_no_inbox_yet(monkeypatch, tmp_path):
    monkeypatch.delenv("CLEANLISTEN_INBOX", raising=False)
    monkeypatch.setattr(learn, "SEND_URL", "")
    assert learn.send_url() == ""
    with pytest.raises(RuntimeError, match="isn't set up"):
        learn.send(exported(tmp_path), "learned")


def test_inbox_down(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = srv.server_port
    srv.server_close()                       # nothing listening there now
    monkeypatch.setenv("CLEANLISTEN_INBOX", f"http://127.0.0.1:{port}/exec")
    with pytest.raises(OSError):
        learn.send(exported(tmp_path), "learned")


def test_too_big_not_sent(inbox, tmp_path, monkeypatch):
    monkeypatch.setattr(learn, "MAX_SEND", 50)
    with pytest.raises(RuntimeError, match="too big"):
        learn.send(exported(tmp_path), "learned")
    assert inbox["posts"] == []
