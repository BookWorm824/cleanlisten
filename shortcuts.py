"""Puts the CleanRead and ReadAloud icons on the desktop and in the Start menu (once), and points
an old CleanView icon at the real CleanView."""
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
# for it, with the same name as the real one's; whichever was made last won (the tester, 2026-10-30).
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


def ensure_readaloud_shortcut(force=False, dirs=None):
    return _ensure_shortcut("ReadAloud", "aloud", "readaloud.ico",
                            "Turn an ebook into an audiobook", force, dirs)


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
    $l.IconLocation = {_q(shown_icon(ico))}
    $l.Description = {_q(desc)}
    $l.Save()
}}
"""
    if _powershell(ps).returncode == 0:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{name} shortcut created. Delete this file to make it again.\n")
        return True
    return False


# ---------- a new logo on the shortcuts ----------
# The slight 3D logos (the owner, 2026-11-15, in CleanView: "E · All of it", "apply to each chat").
# Windows keeps a picture of a shortcut's icon by the icon file's name, so the desktop, Start menu
# and taskbar shortcuts kept the old logo after an update changed icon.ico. As CleanView 1.18.107:
# once each time an app's .ico changes, a copy named by its contents (icon-<mark>.ico), this
# install's shortcuts pointed at it, and Windows told to draw icons again.
ICON_APPS = (("CleanListen", "icon.ico"), ("CleanRead", "cleanread.ico"), ("ReadAloud", "readaloud.ico"))
SHORTCUT_PLACES = r"""@([Environment]::GetFolderPath('Desktop'),
  [Environment]::GetFolderPath('Programs'),
  (Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'),
  (Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\StartMenu'))"""


def icon_mark(path):
    """The first 12 characters of the file's sha1: a new logo, a new mark."""
    import hashlib
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:12]


def shown_icon(ico, here=None):
    """The icon file a shortcut should show: the copy named by its contents if there is one (a
    name Windows hasn't kept an old picture for), else the .ico itself."""
    here = Path(here or HERE)
    try:
        copy = here / f"{Path(ico).stem}-{icon_mark(here / ico)}.ico"
        return copy if copy.exists() else here / ico
    except OSError:
        return here / ico


def new_icons_on_shortcuts(here=None, places=None):
    """Point each app's shortcuts at its new logo, once per change. Returns the apps whose
    shortcuts were changed. here/places: the app folder and shortcut folders (for tests); by
    default only the installed copy does this."""
    if os.name != "nt" or (here is None and not installed_copy()):
        return []
    done = []
    for name, ico in ICON_APPS:
        try:
            if _new_icon_on_shortcuts(Path(here or HERE), name, ico, places):
                done.append(name)
        except Exception as ex:
            try:
                APP_DATA.mkdir(parents=True, exist_ok=True)
                (APP_DATA / "shortcut_icon_problem.txt").write_text(f"{name}: {ex}", encoding="utf8")
            except OSError:
                pass
    return done


def _new_icon_on_shortcuts(here, name, ico, places=None):
    import re
    import shutil
    icon = here / ico
    if not icon.exists():
        return False
    mark = icon_mark(icon)
    seen = APP_DATA / f"icon_shown_{name.lower()}.txt"
    try:
        if seen.read_text(encoding="utf8").strip() == mark:
            return False
    except OSError:
        pass
    stem = Path(ico).stem
    shown = here / f"{stem}-{mark}.ico"
    shutil.copy2(icon, shown)
    where = ("@(" + ", ".join(_q(d) for d in places) + ")") if places is not None else SHORTCUT_PLACES
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
foreach ($d in {where}) {{
    if (-not $d) {{ continue }}
    $p = Join-Path $d '{name}.lnk'
    if (Test-Path -LiteralPath $p) {{
        $l = $ws.CreateShortcut($p)
        if ($l.Arguments.ToLower().Contains({_q(str(here / "launcher.pyw").lower())})) {{
            $l.IconLocation = {_q(shown)} + ',0'; $l.Save(); Write-Output $p }}
    }}
}}
"""
    r = _powershell(ps)
    if r.returncode:
        raise RuntimeError((r.stderr or "").strip()[:300])
    changed = [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]
    if changed:
        import ctypes
        sh = ctypes.windll.shell32
        for p in changed:
            sh.SHChangeNotify(0x2000, 0x0005, ctypes.c_wchar_p(p), None)    # this one changed
        sh.SHChangeNotify(0x08000000, 0, None, None)                      # draw icons again
    for old in here.glob(f"{stem}-*.ico"):
        if re.fullmatch(re.escape(stem) + r"-[0-9a-f]{12}\.ico", old.name) and (old != shown or not changed):
            old.unlink(missing_ok=True)
    APP_DATA.mkdir(parents=True, exist_ok=True)
    seen.write_text(mark, encoding="utf8")
    return bool(changed)
