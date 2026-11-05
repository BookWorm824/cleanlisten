"""Ollama (the local AI helper) only while CleanView, CleanListen or CleanRead are open.

Ollama's installer starts it with Windows and it sat in memory all day (about 4 GB once it had
loaded a model; Lauren, 2026-11-05: "can this be where it only runs when CleanView/Listen/Read
are being used"). The apps start it themselves when they need it (cleanview_ai.start_ollama), so:

- autostart_off(): every time an app opens, take Ollama's shortcut out of the Startup folder
  (its own updates put it back).
- stop_later(): when an app closes, a small background program waits a moment, and once no
  CleanView, CleanListen or CleanRead window or book worker is running and no AI model is
  loaded (it waits up to 7 minutes for one to be let go of), it stops Ollama.

Small on purpose (no numpy) so the closing helper starts fast. Shared idea with CleanView.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLLAMA = os.environ.get("CLEANVIEW_OLLAMA", "http://127.0.0.1:11434")
STARTUP_LINK = (Path(os.environ.get("APPDATA") or Path.home()) / "Microsoft" / "Windows" /
                "Start Menu" / "Programs" / "Startup" / "Ollama.lnk")
# a CleanView, CleanListen or CleanRead window, or a CleanListen book worker
CLEAN_APPS = r"(CleanView|CleanListen|CleanRead)\.pyw|bookrunner\.py"
_NOWIN = 0x08000000 if os.name == "nt" else 0


def installed():
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
        if base and ((Path(base) / "Programs" / "Ollama" / "ollama.exe").exists() or
                     (Path(base) / "Ollama" / "ollama.exe").exists()):
            return True
    return False


def autostart_off(link=None):
    """Take Ollama out of Windows startup. True if its shortcut was there and is gone now."""
    link = Path(link) if link else STARTUP_LINK
    if os.name != "nt" and link == STARTUP_LINK:
        return False
    try:
        if link.exists():
            link.unlink()
            return True
    except OSError:
        pass
    return False


def _get(path, timeout=3):
    with urllib.request.urlopen(OLLAMA + path, timeout=timeout) as r:
        return json.loads(r.read())


def running():
    try:
        _get("/api/tags")
        return True
    except Exception:
        return False


def loaded_models():
    """The AI models Ollama has in memory now ([] for none, None if it isn't answering)."""
    try:
        return _get("/api/ps").get("models") or []
    except Exception:
        return None


def other_apps(skip=()):
    """Process ids of CleanView, CleanListen or CleanRead windows and book workers running now,
    or None if Windows couldn't say (then Ollama is left alone)."""
    if os.name != "nt":
        return None
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and "
          "$_.CommandLine -match '" + CLEAN_APPS + "' } | ForEach-Object { $_.ProcessId }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=90, creationflags=_NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return {int(x) for x in r.stdout.split() if x.strip().isdigit()} - {int(p) for p in skip}


def stop():
    """Stop Ollama: its tray app and the server (and the model runners under it)."""
    for name in ("ollama app.exe", "ollama.exe"):
        subprocess.run(["taskkill", "/IM", name, "/F", "/T"], capture_output=True,
                       creationflags=_NOWIN)


def stop_when_idle(skip=(), settle=8, most=420, every=15):
    """Stop Ollama once nothing of ours uses it. Returns what happened (for the tests)."""
    time.sleep(settle)                   # the closing window and its book workers finish
    end = time.time() + most
    while True:
        if not running():
            return "not running"
        others = other_apps(skip)
        if others is None or others:
            return "in use"              # another app is open: it stops Ollama when it closes
        models = loaded_models()
        if models == []:
            stop()
            return "stopped"
        if models is None:
            return "not running"
        if time.time() > end:
            return "busy"                # something else is using a model: leave it
        time.sleep(every)


def stop_later():
    """From a closing window: check and stop Ollama in a small program of its own, so closing
    isn't held up."""
    if os.name != "nt" or not installed():
        return
    code = ("import sys; sys.path.insert(0, %r); import ollama_care; "
            "ollama_care.stop_when_idle(skip=[%d])" % (str(HERE), os.getpid()))
    try:
        subprocess.Popen([sys.executable, "-c", code], cwd=str(HERE), close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=_NOWIN | 0x00000008 | 0x00000200)  # detached, own group
    except OSError:
        pass
