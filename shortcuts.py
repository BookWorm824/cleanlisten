"""Puts the CleanRead icon on the desktop and in the Start menu (once), and points an old
CleanView icon at the real CleanView."""
import base64
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
APP_DATA = LOCAL / "CleanListen"
# CleanView is its own program now, with its own install (BookWorm824/cleanview,
# "Install CleanView.bat"). CleanListen used to ship an old copy and make a "CleanView" icon
# for it, with the same name as the real one's; whichever was made last won (Jason, 2026-10-30).
CLEANVIEW = LOCAL / "CleanView"
# The installed CleanListen (install.ps1 puts it here). Only it makes or moves the CleanRead
# icon: a copy run from anywhere else (for testing) once made the icon on the owner's PC, and
# the icon led nowhere once that copy was gone (2026-11-04).
INSTALLED = APP_DATA / "app"
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _pythonw():
    # the venv's own pythonw.exe, also when running as CleanListen.exe (launcher.pyw's own name)
    for w in (Path(sys.prefix) / "Scripts" / "pythonw.exe", Path(sys.executable).with_name("pythonw.exe")):
        if w.exists():
            return w
    return Path(sys.executable)


def _q(p):  # PowerShell single-quoted string
    return "'" + str(p).replace("'", "''") + "'"


def _powershell(ps):
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-EncodedCommand", enc], capture_output=True, text=True, **NO_WINDOW)


def real_cleanview():
    """(pythonw.exe, launcher.pyw) of the real CleanView, or None if it isn't installed."""
    pyw, launcher = CLEANVIEW / "venv" / "Scripts" / "pythonw.exe", CLEANVIEW / "app" / "launcher.pyw"
    return (pyw, launcher) if pyw.exists() and launcher.exists() else None


def open_cleanview():
    """Start the real CleanView. False if it isn't installed."""
    real = real_cleanview()
    if not real:
        return False
    subprocess.Popen([str(real[0]), str(real[1])], cwd=str(real[1].parent), **NO_WINDOW)
    return True


def fix_cleanview_shortcut(dirs=None):
    """Point a "CleanView" icon that CleanListen made (it opens CleanListen's launcher with
    "view") at the real CleanView, the way its installer makes it. dirs: the folders to look
    in (default: the desktop and the Start menu). Does nothing if CleanView isn't installed."""
    real = real_cleanview()
    if os.name != "nt" or not real:
        return False
    pyw, launcher = real
    where = ("@(" + ", ".join(_q(d) for d in dirs) + ")" if dirs is not None else
             "@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))")
    ps = f"""
$s = New-Object -ComObject WScript.Shell
foreach ($dir in {where}) {{
    if (-not $dir) {{ continue }}
    $p = Join-Path $dir 'CleanView.lnk'
    if (-not (Test-Path -LiteralPath $p)) {{ continue }}
    $l = $s.CreateShortcut($p)
    if ($l.Arguments -notlike ('*' + {_q(HERE / "launcher.pyw")} + '*view')) {{ continue }}
    $l.TargetPath = {_q(pyw)}
    $l.Arguments = {_q('"' + str(launcher) + '"')}
    $l.WorkingDirectory = {_q(launcher.parent)}
    $l.IconLocation = {_q(launcher.parent / "cleanview.ico")}
    $l.Description = 'Clean up movies and TV shows'
    $l.Save()
}}
"""
    return _powershell(ps).returncode == 0


def ensure_cleanread_shortcut(force=False, dirs=None):
    return _ensure_shortcut("CleanRead", "read", "cleanread.ico",
                            "Check what's in an ebook, or make a clean copy", force, dirs)


def installed_copy():
    """True when this is the installed CleanListen, not a copy run from somewhere else."""
    try:
        return os.path.normcase(str(HERE.resolve())) == os.path.normcase(str(INSTALLED.resolve()))
    except OSError:
        return False


def _ensure_shortcut(name, arg, ico, desc, force=False, dirs=None):
    """Make the icon on the desktop and in the Start menu the first time (a marker file says it
    was made, so one they delete stays deleted), and every time after, put right an icon that
    leads somewhere else or to a program that isn't there. dirs: the folders (for tests)."""
    if os.name != "nt" or not (HERE / (name + ".pyw")).exists() or not installed_copy():
        return False
    marker = APP_DATA / f"{name.lower()}_shortcut_made.txt"
    make = force or not marker.exists()
    launcher = HERE / "launcher.pyw"
    args = '"' + str(launcher) + '" ' + arg
    where = ("@(" + ", ".join(_q(d) for d in dirs) + ")" if dirs is not None else
             "@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))")
    ps = f"""
$s = New-Object -ComObject WScript.Shell
$make = ${'true' if make else 'false'}
foreach ($dir in {where}) {{
    if (-not $dir) {{ continue }}
    $p = Join-Path $dir '{name}.lnk'
    $there = Test-Path -LiteralPath $p
    if (-not $there -and -not $make) {{ continue }}
    $l = $s.CreateShortcut($p)
    if ($there -and -not $make -and $l.Arguments.ToLower().Contains({_q(str(launcher).lower())}) `
            -and $l.TargetPath -and (Test-Path -LiteralPath $l.TargetPath)) {{ continue }}
    $l.TargetPath = {_q(_pythonw())}
    $l.Arguments = {_q(args)}
    $l.WorkingDirectory = {_q(HERE)}
    $l.IconLocation = {_q(HERE / ico)}
    $l.Description = {_q(desc)}
    $l.Save()
}}
"""
    if _powershell(ps).returncode == 0:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{name} shortcut created. Delete this file to make it again.\n")
        return True
    return False
