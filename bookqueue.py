"""The book queue (Lauren, 2026-11-04: "queue several books, a row per book, 3-4 at a time").

Each book you start becomes a row on the "Your books" page. It is prepared (listened to and
checked: cleanlisten.analyze) in its own worker process (bookrunner.py), up to "Books at once"
at a time. Then it waits for you: review stays one book at a time, on the usual review page.
Saving (cleanlisten.render) is a queued step too, so one book can save while another is
prepared.

BookQueue is only the list and its steps (no window, no processes), kept in
APP_DATA/queue.json so it survives closing the window and "Check for updates".
Workers starts and stops the worker processes and hands their messages back.
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent

# the steps a book goes through
WAITING = "waiting"            # waiting its turn to be prepared
PREPARING = "preparing"        # being listened to and checked
READY = "ready"                # ready for you to review
SAVE_WAITING = "save_waiting"  # reviewed, waiting its turn to be saved
SAVING = "saving"              # the clean copy is being saved
DONE = "done"                  # saved
FAILED = "failed"              # ran into a problem
STOPPED = "stopped"            # you pressed Cancel

RUNNING = (PREPARING, SAVING)
# "Check with Claude" on a ready book: it waits and runs as a book being prepared does, with
# job["check_only"] set, and comes back ready to review (stopped or not, the review is kept)
CHECK_WAITING = "Waiting its turn to be checked"
FINISHED = (DONE, FAILED, STOPPED)
AT_ONCE_CHOICES = (1, 2, 3, 4)
DEFAULT_AT_ONCE = 2
# Under this much memory, one book at a time to start with, as CleanView does: each book's
# speech recognition needs its own share, and two at once ran a smaller PC out of memory
# ("bad allocation", 2026-11-04). They can still choose more.
LOW_MEMORY_GB = 12
OUT_OF_MEMORY = ("This computer ran out of memory. Set \u201cBooks at once\u201d to 1, close "
                 "other programs, and press Try again.")

STATUS = {WAITING: "Waiting its turn", PREPARING: "Starting…",
          READY: "Ready to review", SAVE_WAITING: "Waiting its turn to be saved",
          SAVING: "Saving…", DONE: "Saved", FAILED: "Ran into a problem",
          STOPPED: "Stopped"}


def memory_gb():
    """This PC's memory in GB (0 if it can't tell)."""
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in (
                        "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                        "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]
            s = Status()
            s.dwLength = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
                return s.ullTotalPhys / 2 ** 30
            return 0
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except (OSError, ValueError, AttributeError):
        return 0


def default_at_once(gb=None):
    """How many books at once to start with on this PC."""
    gb = memory_gb() if gb is None else gb
    return 1 if 0 < gb < LOW_MEMORY_GB else DEFAULT_AT_ONCE


def plain_error(text):
    """The problem in everyday words when memory ran out ("bad allocation" is what the speech
    recognizer says); anything else as it was."""
    t = str(text or "")
    # ffmpeg says "Cannot allocate memory" when a filter is too long for it, not when the PC is
    # out of memory (CleanView 1.18.26: Jason was told his PC ran out at 33% in use)
    if "error initializing filters" in t.lower() or "' for enable" in t.lower():
        return t
    if any(w in t.lower() for w in ("bad allocation", "bad_alloc", "memoryerror", "out of memory",
                                    "not enough memory", "failed to allocate", "unable to allocate",
                                    # Windows' own words (WinError 1455, 1450, 8)
                                    "paging file is too small", "insufficient system resources",
                                    "not enough storage is available")):
        return OUT_OF_MEMORY
    return t


class Busy(Exception):
    """The same book is being worked on right now."""


def threads_each(at_once, cpus=None):
    """Speech-recognition threads for each book, so the books running together share the
    PC's cores. One book uses at most 8 (more doesn't help one book much). One core is left
    for the window and everything else on the PC: on a 6-core PC one book used all 6 and the
    window seemed frozen (2026-11-05)."""
    cpus = cpus or os.cpu_count() or 2
    spare = cpus - 1 if cpus > 2 else cpus
    return max(2, min(8, spare // max(1, at_once)))


class BookQueue:
    def __init__(self, path, at_once=None):
        self.path = Path(path)
        self.jobs = []
        self.at_once = at_once or default_at_once()
        self.chosen = False          # they picked "Books at once" themselves
        self.load()

    # ---------- keeping it ----------
    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf8"))
        except (OSError, ValueError):
            return
        self.jobs = [j for j in data.get("jobs", []) if isinstance(j, dict) and j.get("key")]
        n = data.get("at_once", self.at_once)
        # 1.14.0-1.14.3 saved 2 on every PC without asking: only a choice of theirs is kept
        self.chosen = bool(data.get("at_once_chosen", n != DEFAULT_AT_ONCE))
        if self.chosen and n in AT_ONCE_CHOICES:
            self.at_once = n

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            keep = [{k: v for k, v in j.items() if not k.startswith("_")} for j in self.jobs]
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"at_once": self.at_once, "at_once_chosen": self.chosen,
                                       "jobs": keep}, indent=1), encoding="utf8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def resume(self):
        """After the window was closed or CleanListen updated: a book that was being prepared
        or saved goes back in line and carries on from where it got to."""
        for j in self.jobs:
            if j["step"] == PREPARING:
                self._set(j, WAITING, "Carries on where it left off")
            elif j["step"] == SAVING:
                self._set(j, SAVE_WAITING, "Waiting its turn to be saved")
        self.save()

    # ---------- the list ----------
    def find(self, key):
        return next((j for j in self.jobs if j["key"] == key), None)

    def running(self):
        return [j for j in self.jobs if j["step"] in RUNNING]

    def unfinished(self):
        return [j for j in self.jobs if j["step"] not in FINISHED]

    def count(self, *steps):
        return sum(1 for j in self.jobs if j["step"] in steps)

    def set_at_once(self, n):
        self.at_once = n if n in AT_ONCE_CHOICES else default_at_once()
        self.chosen = True
        self.save()

    def add(self, spec):
        """A new book (spec: audio, workdir, title, ... see App.start). The same book already
        in the list is replaced, unless it is being worked on right now (Busy)."""
        wd = str(spec["workdir"])
        for old in [j for j in self.jobs if str(j.get("workdir")) == wd]:
            if old["step"] in RUNNING:
                raise Busy(old.get("title", ""))
            self.jobs.remove(old)
        job = dict(spec, key=uuid.uuid4().hex[:12], step=WAITING, status=STATUS[WAITING],
                   frac=0.0, added=time.time())
        self.jobs.append(job)
        self.save()
        return job

    def add_ready(self, spec):
        """A book whose review is already open (from before the queue, or picked up again)."""
        job = self.add(spec)
        self._set(job, READY, STATUS[READY])
        job["frac"] = 1.0
        self.save()
        return job

    def remove(self, key):
        job = self.find(key)
        if job and job["step"] not in RUNNING:
            self.jobs.remove(job)
            self.save()
            return True
        return False

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j["step"] != DONE]
        self.save()

    def move(self, key, by):
        """Up (-1) or down (+1) in line."""
        job = self.find(key)
        if not job:
            return
        i = self.jobs.index(job)
        k = max(0, min(len(self.jobs) - 1, i + by))
        self.jobs.insert(k, self.jobs.pop(i))
        self.save()

    # ---------- what runs next ----------
    def to_start(self):
        """The books to start now: saving goes first (you're waiting for it), then preparing,
        each in line order, up to "Books at once" running together."""
        free = self.at_once - len(self.running())
        if free <= 0:
            return []
        line = ([j for j in self.jobs if j["step"] == SAVE_WAITING] +
                [j for j in self.jobs if j["step"] == WAITING])
        return line[:free]

    def started(self, key):
        job = self.find(key)
        step = SAVING if job["step"] == SAVE_WAITING else PREPARING
        job["task"] = "save" if step == SAVING else ("check" if job.get("check_only") else "prepare")
        self._set(job, step, "Starting the check…" if job["task"] == "check" else STATUS[step])
        job["frac"] = 0.0
        job.pop("error", None)
        self.save()
        return job

    def check(self, key):
        """A book ready to review goes in line to be checked by Claude (or ChatGPT, Gemini)."""
        job = self.find(key)
        if not job or job["step"] != READY:
            return None
        job["check_only"] = True
        self._set(job, WAITING, CHECK_WAITING)
        job["frac"] = 0.0
        self.save()
        return job

    def reviewed(self, key):
        """You pressed "Save clean audiobook" on its review: it goes in line to be saved."""
        job = self.find(key)
        if job:
            self._set(job, SAVE_WAITING, STATUS[SAVE_WAITING])
            job["frac"] = 0.0
            self.save()
        return job

    def stop(self, key):
        """Cancel: a book being prepared or waiting stops (Try again carries on from where it
        got to); a book being saved goes back to ready to review."""
        job = self.find(key)
        if not job:
            return None
        if job.pop("check_only", None) and job["step"] in (WAITING, PREPARING):
            self._set(job, READY, STATUS[READY])     # its review is as it was
            job["frac"] = 1.0
        elif job["step"] in (SAVING, SAVE_WAITING):
            self._set(job, READY, "Saving was stopped. Press Save again on its review.")
        elif job["step"] in (WAITING, PREPARING):
            self._set(job, STOPPED, STATUS[STOPPED])
        self.save()
        return job

    def retry(self, key):
        job = self.find(key)
        if job and job["step"] in (FAILED, STOPPED):
            back = SAVE_WAITING if job.get("task") == "save" else WAITING
            self._set(job, back, STATUS[back])
            job.pop("error", None)
            self.save()
        return job

    # ---------- messages from a worker ----------
    def handle(self, key, msg):
        """A line from the book's worker. Returns "step" when the book moved to another step
        (the page is redrawn), "progress" for a new status line, else None."""
        job = self.find(key)
        if not job:
            return None
        if "p" in msg:
            if job["step"] in RUNNING:
                job["frac"] = max(0.0, min(1.0, float(msg["p"])))
                job["status"] = msg.get("m") or job["status"]
                return "progress"
            return None
        if "log" in msg:
            log = job.setdefault("log", [])
            log.append(str(msg["log"])[:300])
            del log[:-6]
            return None
        if msg.get("done") == "ready" and job["step"] == PREPARING:
            job.pop("check_only", None)
            self._set(job, READY, STATUS[READY])
            job["frac"] = 1.0
            job["found"] = msg.get("found") or {}
            self.save()
            return "step"
        if msg.get("done") == "saved" and job["step"] == SAVING:
            self._set(job, DONE, STATUS[DONE])
            job["frac"] = 1.0
            job["result"] = msg.get("result") or {}
            self.save()
            return "step"
        if msg.get("stopped") and job["step"] in RUNNING:
            self.stop(key)
            return "step"
        if "error" in msg and job["step"] in RUNNING:
            self._fail(job, msg["error"] or "Something went wrong.")
            return "step"
        if "exit" in msg and job["step"] in RUNNING:
            # the worker ended without saying it was done: it crashed or was closed
            self._fail(job, "It stopped unexpectedly. Press Try again — it carries on "
                            "from where it got to.")
            return "step"
        return None

    def _fail(self, job, error):
        if job.pop("check_only", None):
            # only the check didn't happen: the book is still ready to review, and More says why
            found = job.setdefault("found", {})
            found["claude_note"] = f"The AI couldn't check this book ({str(error)[:300]})."
            found["claude_wanted"] = True
            found["check_failed"] = True
            self._set(job, READY, STATUS[READY])
            job["frac"] = 1.0
            self.save()
            return
        job["error"] = str(error)[:500]
        self._set(job, FAILED, STATUS[FAILED])
        self.save()

    @staticmethod
    def _set(job, step, status):
        job["step"], job["status"] = step, status


# ---------------------------------------------------------------------------
# Worker processes
# ---------------------------------------------------------------------------
def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _worker_flags():
    """A book's worker: no console window, and below normal priority, so the window (and
    the rest of the PC) always comes first; the book only slows down while you're using the
    PC. Its ffmpeg runs inherit that priority."""
    if os.name != "nt":
        return 0
    return _no_window() | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)


def kill_tree(proc):
    """Stop a worker and everything it started (ffmpeg, Claude...)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=_no_window(), timeout=15)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


# ---------- Pause and Resume a book ----------
# The owner, 2026-11-12 (CleanView 1.18.66): "should we have a pause buton next to the cancel button
# when a check is happening", then "yes build it". A paused book's worker, and everything it started
# (ffmpeg while saving, the speech model's helpers, Claude's), is frozen where it is and carries on
# from there on Resume. The AI program (Ollama) is shared with CleanRead and CleanView, so it's never
# frozen, even if this book started it: it finishes the question it's on and the answer waits. Other
# books carry on. Cancel, Remove, closing the window and updating resume first (a frozen worker can't
# stop), and nothing is left frozen when CleanListen ends.
NEVER_FREEZE = ("ollama",)


def process_tree(pid):
    """[(pid, exe name)] of a process and everything it started, parents first."""
    if os.name != "nt":
        return [(pid, "")]
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    snap = k.CreateToolhelp32Snapshot(0x2, 0)              # TH32CS_SNAPPROCESS
    info = {}
    if snap and snap != ctypes.c_void_p(-1).value:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            info[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile)
            ok = k.Process32NextW(snap, ctypes.byref(e))
        k.CloseHandle(snap)
    out, seen = [(pid, info.get(pid, (0, ""))[1])], {pid}
    grew = True
    while grew:
        more = [(c, name) for c, (par, name) in info.items() if par in seen and c not in seen and c != par]
        grew = bool(more)
        out += more
        seen |= {c for c, _ in more}
    return out


def freeze(pid, on):
    """Suspend (on) or resume one process. False if it couldn't be."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    nt = ctypes.WinDLL("ntdll")
    fn = nt.NtSuspendProcess if on else nt.NtResumeProcess
    fn.argtypes = (wintypes.HANDLE,)
    h = k.OpenProcess(0x0800, False, pid)                  # PROCESS_SUSPEND_RESUME
    if not h:
        return False
    try:
        return fn(h) == 0
    finally:
        k.CloseHandle(h)


class Workers:
    """One worker process per running book. on_message(key, dict) is called (on a reading
    thread) for every line a worker sends, and once with {"exit": code} when it ends."""

    def __init__(self, on_message, python=None, runner=None, freeze=None, tree=None):
        self.on_message = on_message
        self.python = python or sys.executable
        self.runner = str(runner or HERE / "bookrunner.py")
        self.procs = {}
        self._freeze, self._tree = freeze or globals()["freeze"], tree or process_tree
        self.frozen = {}            # key -> [pids frozen, in order]: the paused books
        self._pause_lock = threading.RLock()
        import atexit
        atexit.register(self.resume_all)     # never leave a book frozen when CleanListen ends

    def pause(self, key):
        """Freeze this book's worker and what it started (not Ollama). True if it's paused."""
        with self._pause_lock:
            proc = self.procs.get(key)
            if proc is None or proc.poll() is not None:
                return False
            if key in self.frozen:
                return True
            done = []
            for pid, name in self._tree(proc.pid):
                if any(n in (name or "").lower() for n in NEVER_FREEZE):
                    continue
                if self._freeze(pid, True):
                    done.append(pid)
            if not done:
                return False
            self.frozen[key] = done
            return True

    def resume(self, key):
        with self._pause_lock:
            for pid in reversed(self.frozen.pop(key, [])):
                self._freeze(pid, False)

    def paused(self, key):
        return key in self.frozen

    def resume_all(self):
        for key in list(self.frozen):
            self.resume(key)

    def start(self, job, task, threads):
        """task: "prepare" or "save". The job's details go in a file in its own folder."""
        key = job["key"]
        wd = Path(job["workdir"])
        wd.mkdir(parents=True, exist_ok=True)
        # "stop" is a file, not a line on the worker's input: on Windows a thread waiting to
        # read a pipe stops other DLLs loading (numpy, the speech model), and the worker froze
        stop_file = wd / f"queue.stop.{uuid.uuid4().hex[:8]}"
        spec = dict({k: v for k, v in job.items() if not k.startswith("_")},
                    task=task, threads=threads, stop_file=str(stop_file), parent=os.getpid())
        spec_path = wd / "queue_task.json"
        spec_path.write_text(json.dumps(spec, indent=1), encoding="utf8")
        err = open(wd / "worker_log.txt", "w", encoding="utf8", errors="replace")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            proc = subprocess.Popen([self.python, self.runner, str(spec_path)], cwd=str(HERE),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                    env=env, creationflags=_worker_flags())
        finally:
            err.close()
        if os.name != "nt":
            try:
                os.setpriority(os.PRIO_PROCESS, proc.pid, 10)
            except (AttributeError, OSError):
                pass
        proc.stop_file = stop_file
        self.procs[key] = proc
        threading.Thread(target=self._read, args=(key, proc), daemon=True,
                         name=f"book worker {key}").start()
        return proc

    def _read(self, key, proc):
        for raw in proc.stdout:
            line = raw.decode("utf8", "replace").strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            # only the book's current worker counts: after Cancel and Try again, the old one
            # may still be finishing, and its "stopped" mustn't stop the new run
            if self.procs.get(key) is proc:
                self.on_message(key, msg)
        code = proc.wait()
        if self.procs.get(key) is proc:
            self.frozen.pop(key, None)
        try:
            proc.stop_file.unlink()
        except OSError:
            pass
        if self.procs.get(key) is proc:
            del self.procs[key]
            self.on_message(key, {"exit": code})

    @staticmethod
    def _ask_to_stop(proc):
        try:
            proc.stop_file.write_text("stop")
        except OSError:
            pass

    def alive(self, key):
        p = self.procs.get(key)
        return p is not None and p.poll() is None

    def stop(self, key, wait=8.0):
        """Ask the worker to stop (it finishes the bit it's on and keeps what it heard), and
        stop it outright if it hasn't after `wait` seconds. Returns at once."""
        proc = self.procs.get(key)
        if proc is None:
            return
        self.resume(key)                    # a frozen worker can't stop
        self._ask_to_stop(proc)

        def later():
            try:
                proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                kill_tree(proc)
        threading.Thread(target=later, daemon=True).start()

    def stop_all(self, wait=5.0):
        """When the window closes: ask every worker to stop, wait a little, then make sure."""
        self.resume_all()                   # a frozen worker can't stop
        procs = list(self.procs.values())
        for p in procs:
            self._ask_to_stop(p)
        end = time.monotonic() + wait
        for p in procs:
            try:
                p.wait(timeout=max(0.1, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for p in procs:
            kill_tree(p)
