"""Puts a CleanView icon on the desktop and in the Start menu (once)."""
import base64
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "CleanListen"


def _pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def open_cleanview():
    """Start CleanView in its own window."""
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
    subprocess.Popen([str(_pythonw()), str(HERE / "CleanView.pyw")], cwd=str(HERE), **flags)


def ensure_cleanview_shortcut(force=False):
    if os.name != "nt":
        return False
    marker = APP_DATA / "cleanview_shortcut_made.txt"
    if marker.exists() and not force:
        return True

    def q(p):  # PowerShell single-quoted string
        return "'" + str(p).replace("'", "''") + "'"

    args = '"' + str(HERE / "launcher.pyw") + '" view'
    ps = f"""
$s = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    if (-not $dir) {{ continue }}
    $l = $s.CreateShortcut((Join-Path $dir 'CleanView.lnk'))
    $l.TargetPath = {q(_pythonw())}
    $l.Arguments = {q(args)}
    $l.WorkingDirectory = {q(HERE)}
    $l.IconLocation = {q(HERE / 'cleanview.ico')}
    $l.Description = 'Clean up movies and TV shows'
    $l.Save()
}}
"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, text=True,
                       creationflags=0x08000000)
    if r.returncode == 0:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        marker.write_text("CleanView shortcut created. Delete this file to make it again.\n")
        return True
    return False
