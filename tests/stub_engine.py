"""A stand-in for cleanlisten.analyze / render, for tests/test_queue.py (the worker loads it
when CLEANLISTEN_ENGINE=stub_engine). How it behaves comes from the job's "stub" entry."""
import json
import os
import time
from pathlib import Path


def _stub(workdir):
    spec = json.loads((Path(workdir) / "queue_task.json").read_text(encoding="utf8"))
    return spec.get("stub") or {}


def analyze(parts, workdir, ebook=None, groups=(), progress=None, log=print, threads=None,
            cancel=None, title="", use_ai=False, use_claude=False, **kw):
    work = Path(workdir)
    stub = _stub(work)
    # loads compiled modules (DLLs) after the worker has started, as the real engine does
    # (numpy, the speech model): a worker that froze doing this once passed with a stub that
    # loaded nothing
    import numpy  # noqa: F401
    import ctypes  # noqa: F401
    (work / "stub_called.json").write_text(json.dumps(dict(kw, groups=list(groups), title=title,
                                                           threads=threads)))
    if stub.get("crash"):
        os._exit(3)                    # like a hard crash in the speech model
    if stub.get("fail"):
        raise RuntimeError(stub["fail"])
    steps = stub.get("steps", 2)
    for n in range(steps):
        if cancel and cancel():
            (work / "transcript.json").write_text("{}")   # what was heard so far is kept
            raise KeyboardInterrupt
        progress(n / max(1, steps - 1), f"Listening to part {n + 1} of {steps}")
        time.sleep(stub.get("delay", 0))
    log("Listened")
    st = {"parts": list(parts), "title": title, "groups": list(groups),
          "scenes": [{"id": 1, "part": 0, "s": 1.0, "e": 7.0, "cut": True},
                     {"id": 2, "part": 0, "s": 9.0, "e": 9.5, "cut": False}],
          "mutes": [{"id": 1, "part": 0, "s": 2.0, "e": 2.3, "on": True},
                    {"id": 2, "part": 0, "s": 3.0, "e": 3.3, "on": True}]}
    (work / "analysis.json").write_text(json.dumps(st))
    return st


def render(workdir, outdir, cuts=None, progress=None, log=print, chapters=False, mutes=None,
           m4b=False, cover=None, author=None):
    progress(0.5, "Saving part 1 of 1")
    (Path(workdir) / "stub_render.json").write_text(json.dumps(
        {"chapters": chapters, "m4b": m4b, "cover": cover, "author": author}))
    return {"mutes": len(mutes), "cuts": len(cuts),
            "cut_minutes": round(sum(c["e"] - c["s"] for c in cuts) / 60, 3), "out": outdir,
            "chapters": None}
