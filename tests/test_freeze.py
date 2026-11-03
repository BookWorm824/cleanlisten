"""Noticing a freeze or a crash in CleanListen and CleanRead (as in CleanView 1.18.9; Jason,
2026-11-03), and a window that a flood of messages, or one bad one, can't stop."""
import json
import queue
import threading
import types

import freezes


class FakeRoot:
    def __init__(self):
        self.afters = []

    def after(self, ms, fn=None):
        self.afters.append((ms, fn))
        return f"after#{len(self.afters)}"

    def after_cancel(self, i):
        pass


def test_a_flood_of_progress_cant_keep_the_window_busy():
    root, q, handled = FakeRoot(), queue.Queue(), []
    for i in range(2000):
        q.put(("progress", i / 2000, f"step {i}"))
    watch = types.SimpleNamespace(doing={})
    freezes.drain(root, q, handled.append, watch=watch)
    assert handled == [("progress", 499 / 2000, "step 499")]
    assert root.afters[-1][0] == 10                 # straight back for the rest
    assert watch.doing["status"] == "step 499"


def test_one_bad_message_doesnt_stop_the_window():
    root, q, handled, errors = FakeRoot(), queue.Queue(), [], []
    for m in (("named", "a"), ("boom",), ("progress", 0.5, "x"), ("done",)):
        q.put(m)

    def handle(msg):
        if msg[0] == "boom":
            raise ValueError("bad")
        handled.append(msg)
    freezes.drain(root, q, handle, errors.append)
    assert [m[0] for m in handled] == ["named", "progress", "done"]
    assert "ValueError: bad" in errors[0]
    assert root.afters[-1][0] == 150


def test_a_freeze_is_written_down_with_what_every_part_was_doing(tmp_path):
    w = freezes.Watch(FakeRoot(), "CleanRead", tmp_path, "cleanread_")
    w.doing.update(page="Finding what to remove…", status="Looking for drinking…")
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="analyze", daemon=True)
    t.start()
    w.note_freeze(25)
    stop.set()
    text = (tmp_path / "cleanread_stopped_last_time.txt").read_text(encoding="utf8")
    assert text.startswith("CleanRead ") and "stopped answering for 25 seconds" in text
    assert "Page: Finding what to remove…" in text and "Doing: Looking for drinking…" in text
    assert "--- analyze ---" in text and "freeze watcher" not in text


def test_next_time_it_is_ready_to_send_once(tmp_path):
    w = freezes.Watch(FakeRoot(), "CleanListen", tmp_path)
    assert w.take_note() is None
    w.add_note("CleanListen closed suddenly.\n\nFatal Python error: Segmentation fault")
    what, path = w.take_note()
    assert what == "closed suddenly"
    data = json.loads(path.read_text(encoding="utf8"))
    assert data["app"] == "CleanListen" and "Segmentation fault" in data["note"]
    assert w.take_note() is None                    # asked about once
    assert (tmp_path / "stopped_before.txt").exists()


def test_a_crash_log_left_behind_becomes_a_note(tmp_path):
    (tmp_path / "crash_log.txt").write_text("Fatal Python error: Aborted", encoding="utf8")
    root = FakeRoot()
    w = freezes.Watch(root, "CleanListen", tmp_path)
    w.start(offer_after_ms=None)
    try:
        assert "closed suddenly" in (tmp_path / "stopped_last_time.txt").read_text(encoding="utf8")
        assert root.afters                                   # the window's beat
    finally:
        w.stop()
    assert (tmp_path / "crash_log.txt").read_text(encoding="utf8") == ""   # a clean close


def test_both_apps_use_it():
    from pathlib import Path
    root = Path(freezes.__file__).parent
    for app, prefix in (("CleanListen.pyw", "''"), ("CleanRead.pyw", "'cleanread_'")):
        src = (root / app).read_text(encoding="utf8")
        assert "freezes.Watch(self, " in src and prefix + ")" in src, app
        assert "freezes.drain(self, self.q, self._handle" in src and "def _handle(self, msg):" in src
        assert "self.watch.stop()" in src
    assert "freezes.py" in json.loads((root / "version.json").read_text())["files"]
