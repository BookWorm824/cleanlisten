"""Noticing a freeze or a crash, for CleanListen and CleanRead (as in CleanView 1.18.9).

Jason, 2026-11-03: CleanView stopped responding during a movie and didn't say why. If the
window doesn't answer for STALL_SECS, what every part of the app was doing is written to
<prefix>stopped_last_time.txt; a hard crash is written by faulthandler to <prefix>crash_log.txt.
Next start they're asked whether to send it in (kind "problem", to CleanListen's inbox).
drain() runs the window's message queue so a flood of messages can't keep it busy, and one
bad message can't stop it."""
import json
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
STALL_SECS = 20
MAX_MESSAGES = 500


def _version():
    try:
        return json.loads((HERE / "version.json").read_text())["version"]
    except Exception:
        return "?"


def memory_note(app):
    """How much memory the app uses and the PC has free ("" if it can't tell)."""
    try:
        import ctypes
        from ctypes import wintypes

        class Mem(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "free", "page_total", "page_free",
                                                   "virt_total", "virt_free", "ext_free")]

        class Proc(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("peak_ws", "ws", "qpp", "qp", "qnpp", "qnp",
                                               "pf", "peak_pf")]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
        m, p = Mem(), Proc()
        m.size, p.size = ctypes.sizeof(m), ctypes.sizeof(p)
        if not (k32.GlobalMemoryStatusEx(ctypes.byref(m)) and
                psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.size)):
            return ""
        gb = 1024 ** 3
        return (f"Memory: {app} uses {p.ws / gb:.1f} GB (at most {p.peak_ws / gb:.1f}); "
                f"the PC has {m.free / gb:.1f} of {m.total / gb:.1f} GB free.")
    except Exception:
        return ""


class Watch:
    """A beat from the window every second, and a watcher thread that writes down what every
    part of the app was doing if the beats stop for STALL_SECS (and, if they start again, how
    long it was). A question box doesn't count: the beats go on under it."""

    def __init__(self, root, app, folder, prefix=""):
        self.root, self.app = root, app
        self.folder = Path(folder)
        self.note_path = self.folder / f"{prefix}stopped_last_time.txt"
        self.crash_path = self.folder / f"{prefix}crash_log.txt"
        self.doing = {}          # "page" and "status", for the note
        self.gone = False
        self._crash_log = None
        self._beat_id = self._offer_id = None

    def add_note(self, text):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.note_path, "a", encoding="utf8") as f:
                f.write(text.replace(str(Path.home()), "~").rstrip() + "\n\n")
        except OSError:
            pass

    def start(self, offer_after_ms=2500):
        import faulthandler
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            if self.crash_path.exists() and self.crash_path.stat().st_size:
                self.add_note(f"{self.app} closed suddenly.\n\n"
                              + self.crash_path.read_text(encoding="utf8", errors="replace"))
            self._crash_log = open(self.crash_path, "w", encoding="utf8")
            faulthandler.enable(self._crash_log, all_threads=True)
        except Exception:
            pass
        self.beat_at = time.monotonic()

        def beat():
            self.beat_at = time.monotonic()
            self._beat_id = self.root.after(1000, beat)
        beat()

        def watch():
            woke, stuck = time.monotonic(), None
            while not self.gone:
                time.sleep(5)
                now = time.monotonic()
                if now - woke > 30:          # the PC was asleep, not the app
                    self.beat_at = now
                woke = now
                if stuck is None and now - self.beat_at > STALL_SECS:
                    stuck = self.beat_at
                    self.note_freeze(now - stuck)
                elif stuck is not None and self.beat_at > stuck:
                    self.add_note(f"It answered again after about {int(self.beat_at - stuck)} seconds.")
                    stuck = None
        threading.Thread(target=watch, daemon=True, name="freeze watcher").start()
        if offer_after_ms is not None:
            self._offer_id = self.root.after(offer_after_ms, self.offer)

    def stop(self):
        """When the window closes: the watcher stops, and the crash log is closed (empty)."""
        self.gone = True
        for i in (self._beat_id, self._offer_id):
            try:
                if i:
                    self.root.after_cancel(i)
            except Exception:
                pass
        try:
            import faulthandler
            faulthandler.disable()
            if self._crash_log:
                self._crash_log.close()
        except Exception:
            pass

    def note_freeze(self, secs):
        """Runs on the watcher's thread, so it reads no part of the window."""
        d = self.doing
        lines = [f"{self.app} {_version()} stopped answering for {int(secs)} seconds "
                 f"({time.strftime('%Y-%m-%d %H:%M')}).",
                 f"Page: {d.get('page', '')}".rstrip(),
                 f"Doing: {d.get('status', '')}".rstrip(),
                 memory_note(self.app)]
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            if names.get(ident) == "freeze watcher":
                continue
            lines.append(f"\n--- {names.get(ident, ident)} ---")
            lines.append("".join(traceback.format_stack(frame)[-12:]).rstrip())
        self.add_note("\n".join(line for line in lines if line))

    def take_note(self):
        """(what happened, the file to send) for last time's freeze or crash, or None."""
        try:
            text = self.note_path.read_text(encoding="utf8").strip()
            self.note_path.replace(self.note_path.with_name(
                self.note_path.name.replace("stopped_last_time", "stopped_before")))
        except OSError:
            return None
        if not text:
            return None
        what = "closed suddenly" if text.startswith(f"{self.app} closed suddenly") else "stopped responding"
        path = self.folder / f"{self.app} {what} {time.strftime('%Y-%m-%d %H-%M')}.json"
        try:
            path.write_text(json.dumps({"app": self.app, "version": _version(), "what": what,
                                        "note": text}, indent=1), encoding="utf8")
        except OSError:
            return None
        return what, path

    def offer(self):
        """It froze or closed suddenly last time: send in what it was doing?"""
        got = self.take_note()
        if not got:
            return
        what, path = got
        try:
            import cleanlisten_learn as learn
            if not learn.send_url():
                return
        except Exception:
            return
        from tkinter import messagebox
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
        if not messagebox.askyesno(
                self.app, f"{self.app} {what} last time. Sorry about that!\n\nSend a note about "
                "what it was doing, so it can be fixed? It has the step it was on and the book's "
                "name. Not the book itself.", parent=self.root):
            return
        done = []

        def go():
            try:
                learn.send(path, "problem")
                done.append(None)
            except Exception as ex:
                done.append(ex)

        def check():
            if self.gone:
                return
            if not done:
                self.root.after(300, check)
            elif done[0] is None:
                messagebox.showinfo(self.app, "Sent. Thank you!", parent=self.root)
            else:
                messagebox.showinfo(self.app, "Couldn't send it just now (check the internet "
                                    f"connection). It's saved here:\n\n{path}", parent=self.root)
        threading.Thread(target=go, daemon=True).start()
        check()


def drain(root, q, handle, on_error=None, watch=None):
    """Handle what the working threads sent: at most MAX_MESSAGES at a time and only the newest
    progress, each on its own (one bad message never stops the window updating), then again
    in 150 ms (or straight away if more are waiting)."""
    import queue
    msgs = []
    try:
        while len(msgs) < MAX_MESSAGES:
            msgs.append(q.get_nowait())
    except queue.Empty:
        pass
    newest = max((i for i, m in enumerate(msgs) if m[0] == "progress"), default=-1)
    try:
        for i, msg in enumerate(msgs):
            if msg[0] == "progress":
                if i != newest:
                    continue
                if watch is not None and len(msg) > 2:
                    watch.doing["status"] = msg[2]
            try:
                handle(msg)
            except Exception:
                if on_error:
                    try:
                        on_error(traceback.format_exc())
                    except Exception:
                        pass
    finally:
        root.after(150 if len(msgs) < MAX_MESSAGES else 10,
                   lambda: drain(root, q, handle, on_error, watch))
