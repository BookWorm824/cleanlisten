"""One of each program at a time, and an "Opening ..." box straight away (the owner, 2026-11-12, via
CleanView 1.18.64: "I only want there to be a single instance of a clean program running. of each
type", "give an indicator box it is opening", "make each program have its name in the opening
box"). CleanListen, CleanRead and ReadAloud each have their own lock; "view" takes none."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest

from conftest import HIDE

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"


@pytest.fixture
def lm(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEANLISTEN_ONE_PREFIX", f"Local\\cltest-{uuid.uuid4().hex}-")
    monkeypatch.delenv("CLEANLISTEN_UPDATE_DONE", raising=False)
    monkeypatch.delenv("CLEANLISTEN_UPDATED", raising=False)
    loader = importlib.machinery.SourceFileLoader("cl_launcher_one", str(ROOT / "launcher.pyw"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_DATA", tmp_path)
    return mod


def holder(name, secs):
    """Another process holding the lock `name` for `secs` seconds."""
    code = textwrap.dedent(f"""
        import ctypes, time
        k = ctypes.WinDLL("kernel32")
        k.CreateMutexW.restype = ctypes.c_void_p
        h = k.CreateMutexW(None, True, {name!r})
        print("held", flush=True)
        time.sleep({secs})
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    p.stdout.readline()
    return p


def test_each_program_has_its_own_lock_and_name(lm):
    names = {a: (lm.app_name(a), lm.one_name(a)) for a in ("", "read", "aloud")}
    assert [n for n, _ in names.values()] == ["CleanListen", "CleanRead", "ReadAloud"]
    assert len({lock for _, lock in names.values()}) == 3
    assert all("CleanView" not in lock for _, lock in names.values())
    assert lm.opening_note("read") != lm.opening_note("") and lm.pid_file("aloud") != lm.pid_file("")


@pytest.mark.skipif(not WINDOWS, reason="Windows locks")
def test_one_holder_and_none_block_each_other(lm):
    p = holder(lm.one_name("read"), 30)
    try:
        assert lm.exists(lm.one_name("read")) and not lm.hold(lm.one_name("read"))
        assert not lm.exists(lm.one_name("")) and lm.hold(lm.one_name(""))      # CleanListen opens
        assert lm.hold(lm.one_name("aloud"))                                     # and ReadAloud
    finally:
        p.kill()
        p.wait()


@pytest.mark.skipif(not WINDOWS, reason="Windows locks")
def test_update_waits_for_the_old_one(lm):
    p = holder(lm.one_name(""), 1.5)
    t = time.time()
    assert lm.hold(lm.one_name(""), wait=20)
    assert time.time() - t > 0.5
    p.wait()


class Click:
    def __init__(self, lm):
        self.calls = []
        self.lm = lm

    def __enter__(self):
        self.ps = [mock.patch.object(self.lm, n, (lambda *a, n=n, **k: self.calls.append((n, a)) or
                                                  (mock.Mock() if n == "start_app" else None)))
                   for n in ("bring_forward", "start_app", "splash")]
        for p in self.ps:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.ps:
            p.stop()


def test_a_click_while_open_brings_it_forward(lm):
    with Click(lm) as c, mock.patch.object(lm, "exists", lambda n: n == lm.one_name("read")):
        assert lm.clicked("read")
        assert [n for n, _ in c.calls] == ["bring_forward"] and c.calls[0][1] == ("read",)
        c.calls.clear()
        assert lm.clicked("")                 # CleanListen isn't open: it opens
        assert [n for n, _ in c.calls] == ["start_app", "splash"]


def test_a_click_while_opening_brings_it_forward(lm):
    with Click(lm) as c, mock.patch.object(lm, "exists", lambda n: False), \
            mock.patch.object(lm, "hold", lambda n, wait=0: False):
        assert lm.clicked("aloud")
    assert [n for n, _ in c.calls] == ["bring_forward"]


def test_update_now_opens_the_new_one(lm, monkeypatch):
    monkeypatch.setenv("CLEANLISTEN_UPDATE_DONE", "1")
    with Click(lm) as c, mock.patch.object(lm, "exists", lambda n: True):
        assert lm.clicked("")
    assert [n for n, _ in c.calls] == ["start_app", "splash"]
    assert os.environ.get("CLEANLISTEN_UPDATE_DONE") == "1"      # passed on to the app part


def test_couldnt_start_apart_runs_here(lm):
    with mock.patch.object(lm, "exists", lambda n: False), mock.patch.object(lm, "hold", lambda n, wait=0: True), \
            mock.patch.object(lm, "start_app", lambda arg="": None):
        assert not lm.clicked("read")


def test_the_app_part_starts_with_its_own_name(lm):
    with mock.patch("subprocess.Popen") as popen, mock.patch.object(lm, "_smart_app_control_off", lambda: False):
        lm.start_app("read")
    args = popen.call_args[0][0]
    assert args[1:] == [str(ROOT / "launcher.pyw"), "read", lm.APP_PART]


def test_another_app_part_won(lm):
    waits = []
    with mock.patch.object(lm, "hold", lambda n, wait=0: waits.append((n, wait))), \
            mock.patch.object(lm, "bring_forward") as fwd, \
            mock.patch.object(lm, "update", side_effect=AssertionError("no update")), \
            mock.patch.object(lm.runpy, "run_path") as run:
        lm.run_app("read")
    fwd.assert_called_once_with("read")
    run.assert_not_called()
    assert waits == [(lm.one_name("read"), 3)]


def test_the_app_part_opens_the_program(lm):
    with mock.patch.object(lm, "hold", lambda n, wait=0: True), mock.patch.object(lm, "update", lambda arg=None: None), \
            mock.patch.object(lm.runpy, "run_path") as run, mock.patch.object(lm.sys, "argv", ["x"]):
        lm.run_app("aloud")
    assert run.call_args[0][0].endswith("ReadAloud.pyw")
    assert lm.pid_file("aloud").read_text(encoding="utf8") == str(os.getpid())
    assert lm.opening_note("aloud").read_text(encoding="utf8") == "Opening ReadAloud…"


def test_after_update_now_it_waits_longer_and_doesnt_check_again(lm, monkeypatch):
    monkeypatch.setenv("CLEANLISTEN_UPDATE_DONE", "1")
    waits = []
    with mock.patch.object(lm, "hold", lambda n, wait=0: waits.append(wait) or True), \
            mock.patch.object(lm, "update", side_effect=AssertionError("no update")), \
            mock.patch.object(lm.runpy, "run_path") as run, mock.patch.object(lm.sys, "argv", ["x"]):
        lm.run_app("")
    assert waits == [lm.RESTART_WAIT] and run.call_args[0][0].endswith("CleanListen.pyw")
    assert "CLEANLISTEN_UPDATE_DONE" not in os.environ             # not passed on to the app


def test_an_update_says_so_and_opens_through_the_new_launcher(lm):
    def upd(arg=None):
        lm.opening(f"Getting {lm.app_name(arg)} 9.9.9…", arg)
        lm.LAUNCHER_CHANGED = True
        return "9.9.9"
    with mock.patch.object(lm, "hold", lambda n, wait=0: True), mock.patch.object(lm, "update", upd), \
            mock.patch.object(lm.runpy, "run_path") as run, mock.patch.object(lm.sys, "argv", ["x"]):
        lm.run_app("read")
        assert lm.sys.argv[1:] == ["read", lm.APP_PART]
    assert run.call_args[0][0].endswith("launcher.pyw")
    assert os.environ.pop("CLEANLISTEN_UPDATED") == "CleanRead was updated to version 9.9.9."
    assert os.environ.pop("CLEANLISTEN_UPDATE_DONE") == "1"
    assert lm.opening_note("read").read_text(encoding="utf8") == "Getting CleanRead 9.9.9…"


def test_view_still_hands_over_without_a_lock(lm):
    src = (ROOT / "launcher.pyw").read_text(encoding="utf8")
    assert 'if _arg not in OWN:\n        main()' in src.replace("\r\n", "\n") and "view" not in lm.OWN


def _box(arg, child_code):
    """How long the "Opening ..." box stays up for a program running child_code. In its own
    process, as in real use (one Tk after another in one process sometimes fails to start)."""
    # (both windows see-through, so nothing pops up while the tests run: conftest.HIDE)
    child_code = HIDE + "\n" + child_code
    code = HIDE + textwrap.dedent(f"""
        import importlib.machinery, importlib.util, subprocess, sys, time
        loader = importlib.machinery.SourceFileLoader("lm_box", {str(ROOT / "launcher.pyw")!r})
        lm = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(lm)
        child = subprocess.Popen([sys.executable, "-c", {child_code!r}])
        t = time.time()
        lm.splash(child, {arg!r})
        print(time.time() - t)
        child.wait()
    """)
    return float(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                timeout=60).stdout.strip())


@pytest.mark.skipif(not WINDOWS, reason="a real window")
def test_the_box_closes_when_the_window_is_up():
    took = _box("read", "import time, tkinter as tk; time.sleep(2); r = tk.Tk(); "
                        "r.after(4000, r.destroy); r.mainloop()")
    assert 1.5 < took < 5.5            # not when the window closes at 6 s


@pytest.mark.skipif(not WINDOWS, reason="a real window")
def test_the_box_closes_when_it_stops():
    assert _box("aloud", "import time; time.sleep(1)") < 4


# --- the update: several files at a time, each tried twice, within UPDATE_MOST, and the box told how far
# it's got (the owner, 2026-11-17, via CleanView 1.18.128: after an update the box "just sits") ---------
class FakeGitHub:
    """Serves a release sealed with a made-up key (never the owner's) that lm is told to trust:
    every update needs the seal since 1.17.81 (test_sealed_updates.py)."""
    def __init__(self, files, lm, version="9.9.9"):
        import hashlib
        import json
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import sign_release
        self.files, self.version = files, version
        self.slow, self.fail_once, self.asked = set(), set(), []
        seed = bytes(range(32))
        lm.PUBLIC_KEY = sign_release.public_of(seed, lm)
        self.data = json.dumps({"version": version, "files": list(files),
                                "sha256": {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}).encode()
        self.sig = sign_release.sign(seed, lm.SEAL_FOR.encode() + self.data, lm).hex().encode()

    def urlopen(self, url, timeout=None):
        import io
        name = url.rsplit("/", 1)[-1]
        self.asked.append(name)
        if name == "version.json":
            body = self.data
        elif name == "version.sig":
            body = self.sig
        else:
            if name in self.slow:
                time.sleep(3)
            if name in self.fail_once:
                self.fail_once.discard(name)
                raise OSError("The handshake operation timed out")
            body = self.files[name]
        r = io.BytesIO(body)
        return mock.MagicMock(__enter__=lambda s: r, __exit__=lambda s, *a: None)


@pytest.fixture
def gh(lm, tmp_path, monkeypatch):
    here = tmp_path / "app"
    here.mkdir()
    (here / "version.json").write_text('{"version": "1.0.0", "files": []}')
    monkeypatch.setattr(lm, "HERE", here)
    g = FakeGitHub({"a.py": b"x = 1\n", "b.txt": b"hello", "CleanRead.pyw": b"y = 2\n"}, lm)
    monkeypatch.setattr(lm.urllib.request, "urlopen", g.urlopen)
    g.here = here
    return g


def test_update_gets_every_file_and_says_how_far(lm, gh):
    assert lm.update("read") == "9.9.9"
    for name, body in gh.files.items():
        assert (gh.here / name).read_bytes() == body
    note = lm.opening_note("read").read_text(encoding="utf8")
    assert note.startswith("Updating CleanRead to 9.9.9") and "(3 of 3)" in note


def test_a_file_that_fails_once_is_tried_again(lm, gh):
    gh.fail_once.add("b.txt")
    assert lm.update("read") == "9.9.9"
    assert gh.asked.count("b.txt") == 2


def test_too_slow_waits_for_next_time(lm, gh, monkeypatch):
    gh.slow.add("CleanRead.pyw")
    monkeypatch.setattr(lm, "UPDATE_MOST", 1)
    t = time.time()
    with pytest.raises(TimeoutError):
        lm.update("read")
    assert time.time() - t < 2.5
    assert not (gh.here / "a.py").exists()          # nothing swapped in: it opens as it is


@pytest.mark.skipif(not WINDOWS, reason="Windows processes")
def test_still_opening_finds_the_one_started_before(lm):
    lm.pid_file("read").write_text(str(os.getpid()), encoding="utf8")
    assert lm.still_opening("read") is None           # this process itself doesn't count
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"], creationflags=0x08000000)
    try:
        lm.pid_file("read").write_text(str(p.pid), encoding="utf8")
        proc = lm.still_opening("read")
        assert proc is not None and proc.poll() is None
    finally:
        p.kill()
        p.wait()
    assert lm.Running(p.pid).poll() is not None
