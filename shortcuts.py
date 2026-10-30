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
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


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


def ensure_cleanread_shortcut(force=False):
    return _ensure_shortcut("CleanRead", "read", "cleanread.ico",
                            "Check what's in an ebook, or make a clean copy", force)


def _ensure_shortcut(name, arg, ico, desc, force=False):
    if os.name != "nt" or not (HERE / (name + ".pyw")).exists():
        return False
    marker = APP_DATA / f"{name.lower()}_shortcut_made.txt"
    if marker.exists() and not force:
        return True
    args = '"' + str(HERE / "launcher.pyw") + '" ' + arg
    ps = f"""
$s = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    if (-not $dir) {{ continue }}
    $l = $s.CreateShortcut((Join-Path $dir '{name}.lnk'))
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
