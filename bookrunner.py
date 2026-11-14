"""One book's worker for the book queue (bookqueue.py): prepares it (cleanlisten.analyze) or
saves it (cleanlisten.render) in its own process, so a crash or a long step in one book never
takes the window down, and each book's speech recognition gets its own share of the PC.

    pythonw bookrunner.py <APP_DATA/jobs/<key>/queue_task.json>

It sends one JSON object per line on stdout: {"p": 0.42, "m": "Listening..."} for progress,
{"log": ...}, then {"done": "ready", "found": {...}} or {"done": "saved", "result": {...}},
{"stopped": true} or {"error": "..."}. Its stop file (spec["stop_file"], written by the window)
or the window going away stops it after the bit it's on; what it already heard is kept.
"""
import faulthandler
import importlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import freezes   # awake(): the PC doesn't go to sleep while this book is worked on

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_out_lock = threading.Lock()


def send(**msg):
    with _out_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def window_gone(pid):
    """Has the window that started this worker closed (or crashed)?"""
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, int(pid))       # SYNCHRONIZE
    if not h:
        return True
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0   # it has ended
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def watch_for_stop(stop, stop_file, parent):
    """The window asks a book to stop by writing its stop file (Cancel, closing, updating);
    a window that's gone stops it too. (Not by reading stdin: on Windows a thread waiting on
    a pipe stops other DLLs loading, and the worker froze while importing numpy.)"""
    def run():
        while not stop.is_set():
            try:
                if (stop_file and os.path.exists(stop_file)) or window_gone(parent):
                    stop.set()
                    return
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()


def lock_book(workdir, stop, say):
    """Only one worker per book at a time: a worker from before an update (or a Cancel and Try
    again) may still be finishing; wait for it, so two never write the same transcript."""
    path = Path(workdir) / "queue.lock"
    fh = open(path, "a+b")
    if os.name != "nt":
        return fh
    import msvcrt
    told = False
    while True:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return fh
        except OSError:
            if stop.is_set():
                raise KeyboardInterrupt
            if not told:
                say(0.0, "Waiting for the last run of this book to stop…")
                told = True
            time.sleep(0.5)


def found_counts(st):
    scenes = st.get("scenes", [])
    mutes = st.get("mutes", [])
    return {"words": sum(1 for m in mutes if m.get("on", True)),
            "passages": sum(1 for s in scenes if s.get("cut", True)),
            "unticked": (sum(1 for m in mutes if not m.get("on", True)) +
                         sum(1 for s in scenes if not s.get("cut", True))),
            "claude_note": st.get("claude_note", ""),
            "claude_checked": bool(st.get("claude_checked")),
            "claude_wanted": bool(st.get("claude_wanted") or st.get("claude_note"))}


def prepare(engine, spec, stop, say, log):
    st = engine.analyze(
        spec["audio"], spec["workdir"], ebook=spec.get("ebook"), groups=spec["groups"],
        use_ai=spec.get("use_ai", False), use_claude=spec.get("use_claude", False),
        **spec.get("filter_args", {}), title=spec.get("title", ""),
        threads=spec.get("threads"), progress=say, log=log, cancel=stop.is_set)
    st["title"] = spec.get("title") or st.get("title", "")
    (Path(spec["workdir"]) / "analysis.json").write_text(json.dumps(st, indent=1))
    send(done="ready", found=found_counts(st))


def check(engine, spec, stop, say, log):
    """"Check with Claude" (or ChatGPT, Gemini) on "Your books" (the owner, 2026-11-14: "you need
    a button that I can hit to just check the book again"): it reads a book that is ready to
    review, with everything found and your ticks, as the review page's button does. Nothing is
    listened to again; your own ticks are never undone."""
    import cleanlisten_claude as cc
    path = Path(spec["workdir"]) / "analysis.json"
    st = json.loads(path.read_text())
    asr = engine.load_asr(spec["workdir"], st["parts"])
    cc.review(st, asr, progress=say, cancel=stop.is_set)
    st["claude_wanted"] = True
    engine.write_safely(path, json.dumps(st, indent=1))
    log(st.get("claude_note", ""))
    send(done="ready", found=found_counts(st))


def save(engine, spec, stop, say, log):
    a = json.loads((Path(spec["workdir"]) / "analysis.json").read_text())
    # what was ticked on the review page (it saved the ticks into the analysis)
    cuts = [sc for sc in a["scenes"] if sc.get("cut", True)]
    mutes = [m for m in a["mutes"] if m.get("on", True)]
    res = engine.render(spec["workdir"], spec["outdir"], cuts, progress=say, log=log,
                        chapters=spec.get("split", False), mutes=mutes,
                        m4b=spec.get("m4b", False), cover=spec.get("cover"),
                        author=spec.get("author") or None,
                        chapters_dir=spec.get("chapters_dir") or None,
                        m4b_dir=spec.get("m4b_dir") or None, abs_layout=spec.get("abs", False),
                        series=spec.get("series") or "", series_no=spec.get("series_no") or "",
                        cover_online=spec.get("cover_online", False))
    send(done="saved", result=res)


def main(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf8"))
    workdir = Path(spec["workdir"])
    try:
        faulthandler.enable()          # a hard crash goes to worker_log.txt (stderr)
    except Exception:
        pass
    freezes.awake().__enter__()   # the PC stays awake until this worker ends (2026-11-09)
    stop = threading.Event()
    watch_for_stop(stop, spec.get("stop_file"), spec.get("parent"))
    say = lambda f, m: send(p=round(float(f), 4), m=str(m))
    log = lambda m: send(log=str(m))
    try:
        lock = lock_book(workdir, stop, say)
        # (CLEANLISTEN_ENGINE: the tests use a stand-in engine)
        engine = importlib.import_module(os.environ.get("CLEANLISTEN_ENGINE") or "cleanlisten")
        {"prepare": prepare, "check": check, "save": save}[spec["task"]](engine, spec, stop, say, log)
        lock.close()
    except KeyboardInterrupt:
        send(stopped=True)
    except Exception as ex:
        details = traceback.format_exc()
        try:     # (render keeps ffmpeg's own words in save_error.txt)
            (workdir / "last_error.txt").write_text(details, encoding="utf8")
        except OSError:
            pass
        send(error=str(ex) or ex.__class__.__name__)


if __name__ == "__main__":
    main(sys.argv[1])
