"""CleanListen launcher: checks GitHub for a newer version, updates the
program files if there is one, then opens the app (CleanListen, or CleanView
when started with "view"). If the check fails (offline, GitHub down) the app
simply opens as-is."""
import json
import os
import runpy
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "update.json").read_text())   # {"repo": "...", "branch": "main"}
RAW = f"https://raw.githubusercontent.com/{CONFIG['repo']}/{CONFIG.get('branch', 'main')}/"


def _ver(s):
    return tuple(int(x) for x in str(s).split(".") if x.isdigit())


def update():
    local = json.loads((HERE / "version.json").read_text())
    with urllib.request.urlopen(RAW + "version.json", timeout=4) as r:
        remote = json.loads(r.read().decode("utf8"))
    if _ver(remote["version"]) <= _ver(local["version"]):
        return None
    # download everything first, check it, and only then swap files in
    staged = {}
    for name in remote["files"]:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"unexpected file name {name}")
        with urllib.request.urlopen(RAW + name, timeout=20) as r:
            data = r.read()
        if name.endswith((".py", ".pyw")):
            compile(data, name, "exec")  # refuse a broken download
        staged[name] = data
    for name, data in staged.items():
        fd, tmp = tempfile.mkstemp(dir=HERE)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, HERE / name)
    (HERE / "version.json").write_text(json.dumps(remote, indent=1))
    return remote["version"]


if __name__ == "__main__":
    note = None
    try:
        new = update()
        if new:
            note = f"CleanListen was updated to version {new}."
    except Exception as ex:  # never block the app over an update problem
        try:
            (HERE / "update_error.txt").write_text(str(ex), encoding="utf8")
        except Exception:
            pass
    if note:
        os.environ["CLEANLISTEN_UPDATED"] = note
    app = "CleanView.pyw" if (len(sys.argv) > 1 and sys.argv[1] == "view"
                              and (HERE / "CleanView.pyw").exists()) else "CleanListen.pyw"
    sys.argv = [str(HERE / app)]
    runpy.run_path(str(HERE / app), run_name="__main__")
