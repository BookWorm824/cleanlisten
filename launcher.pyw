"""CleanListen launcher: checks GitHub for a newer version, updates the
program files if there is one, then opens the app (CleanListen, or CleanRead
when started with "read", ReadAloud with "aloud"; "view" opens CleanView.pyw, which hands over
to the real CleanView, its own program now). If the check fails (offline, GitHub down) the app
simply opens as-is."""
import json
import os
import runpy
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# {"repo": "...", "branch": "main"}. A fresh install from 1.14.1's setup had no update.json
# (it wasn't on version.json's list), and this line stopped CleanListen before its window
# opened (2026-11-04), so it's on the list now and missing or broken means the usual place.
try:
    CONFIG = json.loads((HERE / "update.json").read_text())
    CONFIG["repo"]
except (OSError, ValueError, KeyError, TypeError):
    CONFIG = {"repo": "BookWorm824/cleanlisten", "branch": "main"}
RAW = f"https://raw.githubusercontent.com/{CONFIG['repo']}/{CONFIG.get('branch', 'main')}/"


def _ver(s):
    return tuple(int(x) for x in str(s).split(".") if x.isdigit())


# ---------- each app's own name in Task Manager ----------
# Task Manager names a program by its .exe's description, so CleanListen and CleanRead showed
# as "Python" (Jason, 2026-11-03). As in CleanView 1.18.9: CleanListen.exe / CleanRead.exe are
# copies of the venv's base pythonw.exe in venv\CleanListen and venv\CleanRead, with
# python312.dll beside them and their description and icon changed; each finds the venv
# through venv\pyvenv.cfg one folder up, like Scripts\pythonw.exe does. (Not in Scripts:
# sherpa-onnx put an onnxruntime.dll there, which an .exe in that folder would load first.)
# The changed .exe has no signature, so Smart App Control would block it: it's only made while
# that's off, and only used once a test run of it has worked (never tried again once it failed).
OWN = {"": ("CleanListen", "icon.ico"), "read": ("CleanRead", "cleanread.ico"),
       "aloud": ("ReadAloud", "readaloud.ico")}
APPS = {"view": ("CleanView", "CleanView.pyw"), "read": ("CleanRead", "CleanRead.pyw"),
        "aloud": ("ReadAloud", "ReadAloud.pyw")}
OWN_BUILD = 1          # raise to make every copy again


def _smart_app_control_off():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\CI\Policy") as k:
            return winreg.QueryValueEx(k, "VerifiedAndReputablePolicyState")[0] == 0
    except FileNotFoundError:
        return True        # Windows without Smart App Control
    except OSError:
        return False


def _unsign(path):
    """Drop the signature (now wrong) from the end of an .exe."""
    import struct
    data = bytearray(path.read_bytes())
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    opt = pe + 24
    dirs = opt + (112 if struct.unpack_from("<H", data, opt)[0] == 0x20B else 96)
    at, size = struct.unpack_from("<II", data, dirs + 4 * 8)
    if size and at + size <= len(data):
        del data[at:]
        struct.pack_into("<II", data, dirs + 4 * 8, 0, 0)
        path.write_bytes(bytes(data))


def _version_info(name):
    """A VS_VERSIONINFO resource whose description and product name are `name`."""
    import struct

    def pad(b):
        return b + b"\0" * (-len(b) % 4)

    def block(key, value=b"", children=(), text=True, value_len=None):
        body = pad(struct.pack("<HHH", 0, 0, 0) + (key + "\0").encode("utf-16-le"))
        body = pad(body + value) if children else body + value
        body += b"".join(pad(c) for c in children)
        if value_len is None:
            value_len = len(value) // 2 if text else len(value)
        return struct.pack("<HHH", len(body), value_len, int(text)) + body[6:]

    def string(key, val):
        return block(key, (val + "\0").encode("utf-16-le"))

    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, 0x10000, 0, 0x10000, 0, 0x3F, 0,
                        0x40004, 1, 0, 0, 0)
    table = block("040904B0", children=[string(k, v) for k, v in (
        ("CompanyName", name), ("FileDescription", name), ("FileVersion", "1.0.0.0"),
        ("InternalName", name), ("OriginalFilename", name + ".exe"),
        ("ProductName", name), ("ProductVersion", "1.0.0.0"))])
    var = block("VarFileInfo", children=[
        block("Translation", struct.pack("<HH", 0x0409, 0x04B0), text=False)])
    return block("VS_VERSION_INFO", fixed, [block("StringFileInfo", children=[table]), var],
                 text=False)


def _rename_exe(path, name, icon):
    """Give an .exe the description `name` and the icons from the .ico file `icon`."""
    import ctypes
    import struct
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = (wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
    k32.FreeLibrary.argtypes = (wintypes.HMODULE,)
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.BeginUpdateResourceW.argtypes = (wintypes.LPCWSTR, wintypes.BOOL)
    k32.UpdateResourceW.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.WORD, ctypes.c_void_p, wintypes.DWORD)
    k32.EndUpdateResourceW.argtypes = (wintypes.HANDLE, wintypes.BOOL)
    names_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p)
    langs_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p,
                                  ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p)
    k32.EnumResourceNamesW.argtypes = (wintypes.HMODULE, ctypes.c_void_p, names_cb,
                                       ctypes.c_void_p)
    k32.EnumResourceLanguagesW.argtypes = (wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p,
                                           langs_cb, ctypes.c_void_p)
    RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16

    def res_id(p):        # a number, or a name (kept as a string)
        return p if p < 0x10000 else ctypes.wstring_at(p)

    def as_arg(v, keep):
        if isinstance(v, int):
            return ctypes.c_void_p(v)
        buf = ctypes.create_unicode_buffer(v)
        keep.append(buf)
        return ctypes.cast(buf, ctypes.c_void_p)

    old = []              # (type, name, language) of every icon and version resource
    mod = k32.LoadLibraryExW(str(path), None, 0x2)      # LOAD_LIBRARY_AS_DATAFILE
    if not mod:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for rt in (RT_ICON, RT_GROUP_ICON, RT_VERSION):
            found = []
            k32.EnumResourceNamesW(mod, rt, names_cb(
                lambda m, t, n, p: found.append(res_id(n)) or True), None)
            for n in found:
                keep = []
                k32.EnumResourceLanguagesW(mod, rt, as_arg(n, keep), langs_cb(
                    lambda m, t, nn, lang, p, n=n: old.append((rt, n, lang)) or True), None)
    finally:
        k32.FreeLibrary(mod)

    ico = Path(icon).read_bytes()
    count = struct.unpack_from("<H", ico, 4)[0]
    images, group = [], struct.pack("<HHH", 0, 1, count)
    for i in range(count):
        w, h, colors, _, planes, bits, size, at = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * i)
        images.append(ico[at:at + size])
        group += struct.pack("<BBBBHHIH", w, h, colors, 0, planes, bits, size, i + 1)
    new = [(RT_ICON, i + 1, img) for i, img in enumerate(images)]
    new += [(RT_GROUP_ICON, 1, group), (RT_VERSION, 1, _version_info(name))]

    h = k32.BeginUpdateResourceW(str(path), False)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    keep = []
    try:
        for rt, n, lang in old:
            if not k32.UpdateResourceW(h, rt, as_arg(n, keep), lang, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        for rt, n, data in new:
            buf = ctypes.create_string_buffer(data, len(data))
            keep.append(buf)
            if not k32.UpdateResourceW(h, rt, n, 0x0409, buf, len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        k32.EndUpdateResourceW(h, True)
        raise
    if not k32.EndUpdateResourceW(h, False):
        raise ctypes.WinError(ctypes.get_last_error())


def make_own_exe(name, icon, folder=None, base=None):
    """<name>.exe in `folder` (venv\\<name>), made once and tried out. Returns its path, or
    None to keep using pythonw.exe."""
    import shutil
    import subprocess
    if os.name != "nt" or (folder is None and sys.prefix == sys.base_prefix):
        return None
    folder = Path(folder or Path(sys.prefix) / name)
    base = Path(base or sys.base_prefix)
    exe = folder / (name + ".exe")
    try:
        st = (base / "pythonw.exe").stat()
        stamp = f"{OWN_BUILD} {base} {st.st_size} {int(st.st_mtime)}"
    except OSError:
        return None
    done, failed = folder / "made.txt", folder / "failed.txt"
    for f in (done, failed):
        try:
            if f.read_text(encoding="utf8").splitlines()[0] == stamp:
                return exe if f is done and exe.exists() else None
        except (OSError, IndexError):
            pass
    try:
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        for dll in base.glob("*.dll"):          # python312.dll, python3.dll, vcruntime140...
            shutil.copy2(dll, folder / dll.name)
        shutil.copy2(base / "pythonw.exe", exe)
        _unsign(exe)
        _rename_exe(exe, name, icon)
        out = folder / "tried.txt"
        out.unlink(missing_ok=True)
        subprocess.run([str(exe), "-c", "import sys, tkinter; open(sys.argv[1], 'w').write(sys.prefix)",
                        str(out)], timeout=120, creationflags=0x08000000,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if Path(out.read_text(encoding="utf8")).resolve() != folder.parent.resolve():
            raise RuntimeError(f"{exe.name} used {out.read_text(encoding='utf8')}")
        out.unlink(missing_ok=True)
        done.write_text(stamp, encoding="utf8")
        return exe
    except Exception as ex:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            failed.write_text(f"{stamp}\n{type(ex).__name__}: {ex}", encoding="utf8")
        except OSError:
            pass
        return None


def as_own_exe(arg=""):
    """Start this launcher again as CleanListen.exe or CleanRead.exe. True if that started."""
    import subprocess
    if arg not in OWN or os.name != "nt":
        return False
    name, icon = OWN[arg]
    if Path(sys.executable).name.lower() == (name + ".exe").lower() or not _smart_app_control_off():
        return False
    exe = make_own_exe(name, HERE / icon)
    if not exe:
        return False
    try:
        subprocess.Popen([str(exe), str(Path(__file__).resolve())] + sys.argv[1:], cwd=str(HERE))
        return True
    except OSError as ex:      # blocked after all: don't try again
        try:
            (exe.parent / "failed.txt").write_text(
                (exe.parent / "made.txt").read_text(encoding="utf8") + f"\n{ex}", encoding="utf8")
        except OSError:
            pass
        return False


def start_again(note):
    """After an update, start the launcher just downloaded (without checking again), so what's
    new in it works now: the first start after 1.13.0 still showed "Python" in Task Manager,
    because this, the old launcher, opened the app itself (Jason, 2026-11-03)."""
    import subprocess
    env = dict(os.environ, CLEANLISTEN_UPDATED=note, CLEANLISTEN_UPDATE_DONE="1")
    try:
        subprocess.Popen([sys.executable, str(HERE / "launcher.pyw")] + sys.argv[1:], cwd=str(HERE), env=env)
        return True
    except OSError:
        return False


LAUNCHER_CHANGED = False      # the update brought a new launcher.pyw


def update(arg=None):
    local = json.loads((HERE / "version.json").read_text())
    with urllib.request.urlopen(RAW + "version.json", timeout=4) as r:
        remote = json.loads(r.read().decode("utf8"))
    if _ver(remote["version"]) <= _ver(local["version"]):
        return None
    if arg is not None:
        opening(f"Getting {app_name(arg)} {remote['version']}\u2026", arg)
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
    global LAUNCHER_CHANGED
    old = HERE / "launcher.pyw"
    LAUNCHER_CHANGED = "launcher.pyw" in staged and (
        not old.exists() or old.read_bytes() != staged["launcher.pyw"])
    for name, data in staged.items():
        fd, tmp = tempfile.mkstemp(dir=HERE)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, HERE / name)
    (HERE / "version.json").write_text(json.dumps(remote, indent=1))
    return remote["version"]


# ---------- one of each program at a time, and a window straight away ----------
# The owner, 2026-11-12 (CleanView 1.18.64, then "pass to read aloud also. make each program have
# its name in the opening box"): "it can take several second and gives no indication it is opening.
# so i click again and get multiple windows open. I only want there to be a single instance of a
# clean program running. of each type", "The program can take time to open if it needs, but give an
# indicator box it is opening".
# The part started from the Start menu (clicked) shows "Opening CleanListen..." (or CleanRead,
# ReadAloud) at once and starts the program as its own process (run_app, "--app"), which holds that
# program's lock for as long as it runs. A click while it's open, or while it's opening, brings that
# window forward instead. Each program has its own lock, so CleanListen, CleanRead, ReadAloud and
# CleanView never stop one another. "view" (the hand-over to the real CleanView) takes none: CleanView's
# own launcher does that. "Update now" / "Check for updates" (CLEANLISTEN_UPDATE_DONE) starts a new
# one while the old one closes: it waits for the old one to let go (RESTART_WAIT).
APP_PART = "--app"
LOCK_PREFIX = os.environ.get("CLEANLISTEN_ONE_PREFIX") or "Local\\"
RESTART_WAIT = 90
SPLASH_MOST = 180             # seconds; the box says "Opening" at most this long
APP_DATA = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "CleanListen"
_held = []                    # locks this process holds until it ends


def app_name(arg=""):
    return OWN.get(arg, OWN[""])[0]


def one_name(arg=""):
    """The lock that says this program is open."""
    return f"{LOCK_PREFIX}{app_name(arg)}-open"


def opening_name(arg=""):
    """The lock that says this program is being opened (a second click right away)."""
    return one_name(arg) + "-opening"


def opening_note(arg=""):
    return APP_DATA / f"opening_{app_name(arg)}.txt"     # what its box says (run_app writes it)


def pid_file(arg=""):
    return APP_DATA / f"open_pid_{app_name(arg)}.txt"    # which process it is, to bring it forward


def _restarting():
    return bool(os.environ.get("CLEANLISTEN_UPDATE_DONE"))


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


def hold(name, wait=0.0):
    """Take the named lock for as long as this process runs. False if another process has it
    (after waiting up to `wait` seconds for it to be let go). Not knowing never stops a program
    opening."""
    if os.name != "nt":
        return True
    try:
        k = _kernel32()
        h = k.CreateMutexW(None, False, name)
        if not h:
            return True
        got = k.WaitForSingleObject(h, int(wait * 1000))
        if got in (0, 0x80):          # ours, or let go by a process that ended
            _held.append(h)
            return True
        k.CloseHandle(h)
        return False
    except Exception:
        return True


def exists(name):
    """Does some process hold (or wait on) the named lock?"""
    if os.name != "nt":
        return False
    try:
        k = _kernel32()
        h = k.OpenMutexW(0x00100000, False, name)        # SYNCHRONIZE
        if h:
            k.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def family(pid):
    """A process and every process it started, and they started (a venv's pythonw.exe starts the
    real Python as its own process, which then owns the window)."""
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
    parents = {}
    if snap and snap != ctypes.c_void_p(-1).value:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            parents[e.th32ProcessID] = e.th32ParentProcessID
            ok = k.Process32NextW(snap, ctypes.byref(e))
        k.CloseHandle(snap)
    out, grew = {pid}, True
    while grew:
        more = {c for c, par in parents.items() if par in out and c not in out and c != par}
        grew = bool(more)
        out |= more
    return out


def windows_of(pid=None, title=None):
    """The visible top-level windows of a process and the ones it started (or, with title, of
    any other process whose Tk window's title starts with it)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    found = []
    each = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    pids = family(pid) if pid is not None else set()

    def look(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids:
            found.append(hwnd)
        elif title is not None and owner.value != os.getpid():
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(hwnd, cls, 64)
            text = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, text, 256)
            if cls.value == "TkTopLevel" and text.value.startswith(title):
                found.append(hwnd)
        return True
    u.EnumWindows(each(look), 0)
    return found


def bring_forward(arg=""):
    """Bring the program that's already open (or opening) to the front. True if found."""
    if os.name != "nt":
        return False
    import ctypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    try:
        pid = int(pid_file(arg).read_text(encoding="utf8").strip())
    except (OSError, ValueError):
        pid = None
    wins = (windows_of(pid) if pid else []) or windows_of(title=app_name(arg))
    for hwnd in wins[:1]:
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)                          # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return True
    return False


def opening(text, arg=""):
    """What the "Opening ..." box says now."""
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        opening_note(arg).write_text(text, encoding="utf8")
    except OSError:
        pass


def start_app(arg=""):
    """Start the program as its own process: as CleanListen.exe / CleanRead.exe / ReadAloud.exe
    where it can be (its name in Task Manager), else this Python. None if neither started."""
    import subprocess
    exe = None
    try:
        name, icon = OWN.get(arg, OWN[""])
        if (os.name == "nt" and Path(sys.executable).name.lower() != (name + ".exe").lower()
                and _smart_app_control_off()):
            exe = make_own_exe(name, HERE / icon)
    except Exception:          # never block the app over its name
        exe = None
    for prog in ([str(exe)] if exe else []) + [sys.executable]:
        try:
            return subprocess.Popen([prog, str(Path(__file__).resolve())] + ([arg] if arg else [])
                                    + [APP_PART], cwd=str(HERE))
        except OSError as ex:
            if exe and prog == str(exe):     # blocked after all: don't try it again
                try:
                    (exe.parent / "failed.txt").write_text(
                        (exe.parent / "made.txt").read_text(encoding="utf8") + f"\n{ex}",
                        encoding="utf8")
                except OSError:
                    pass
    return None


def splash(child, arg="", most=SPLASH_MOST):
    """A small "Opening CleanListen..." box until the program's own window is up (or it has
    stopped, or `most` seconds)."""
    import time
    import tkinter as tk
    from tkinter import ttk
    name = app_name(arg)
    root = tk.Tk()
    root.title(f"Opening {name}")      # not the program's own title, so a click can't mistake it
    try:
        root.iconbitmap(str(HERE / OWN.get(arg, OWN[""])[1]))
    except Exception:
        pass
    root.configure(bg="#FFFFFF")
    root.resizable(False, False)
    tk.Label(root, text=f"Opening {name}…", bg="#FFFFFF", fg="#23211F",
             font=("Segoe UI", 14, "bold")).pack(padx=40, pady=(22, 4))
    said = tk.StringVar(value="This can take a few seconds.")
    tk.Label(root, textvariable=said, bg="#FFFFFF", fg="#5C5852",
             font=("Segoe UI", 10)).pack(padx=40)
    bar = ttk.Progressbar(root, mode="indeterminate", length=260)
    bar.pack(padx=40, pady=(12, 22))
    bar.start(12)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+"
                  f"{(root.winfo_screenheight() - h) // 2 - 40}")
    start = time.time()
    try:                       # the program's window may come to the front itself
        import ctypes
        for p in family(child.pid):
            ctypes.WinDLL("user32").AllowSetForegroundWindow(p)
    except Exception:
        pass

    def check():
        wins = windows_of(child.pid)
        if wins:                # its window is up: hand it the front, then go
            try:
                import ctypes
                ctypes.WinDLL("user32").SetForegroundWindow(wins[0])
            except Exception:
                pass
        if child.poll() is not None or wins or time.time() - start > most:
            bar.stop()
            root.destroy()
            return
        try:
            text = opening_note(arg).read_text(encoding="utf8").strip()
            if text and text != said.get():
                said.set(text)
        except OSError:
            pass
        root.after(200, check)
    root.after(200, check)
    root.mainloop()


def run_app(arg=""):
    """The part that is the program: one at a time, look for an update, then open the window."""
    name = app_name(arg)
    restart = _restarting()
    if not hold(one_name(arg), wait=RESTART_WAIT if restart else 3):
        bring_forward(arg)                  # two clicks a moment apart: the other one won
        return
    try:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        pid_file(arg).write_text(str(os.getpid()), encoding="utf8")
    except OSError:
        pass
    note = None
    try:
        # CLEANLISTEN_UPDATE_DONE: started again right after an update ("Check for updates"), so
        # don't look again, and don't pass it on to anything the program starts
        new = None if os.environ.pop("CLEANLISTEN_UPDATE_DONE", None) else update(arg)
        if new:
            note = f"{name} was updated to version {new}."
    except Exception as ex:  # never block the app over an update problem
        new = None
        try:
            (HERE / "update_error.txt").write_text(str(ex), encoding="utf8")
        except Exception:
            pass
    if note:
        os.environ["CLEANLISTEN_UPDATED"] = note
    if new and LAUNCHER_CHANGED:
        # open it through the new launcher just downloaded, so what's new in it works now (this
        # process keeps the lock: taking it again from the same process is allowed)
        os.environ["CLEANLISTEN_UPDATE_DONE"] = "1"
        sys.argv = [str(HERE / "launcher.pyw")] + ([arg] if arg else []) + [APP_PART]
        runpy.run_path(str(HERE / "launcher.pyw"), run_name="__main__")
        return
    opening(f"Opening {name}…", arg)
    app = APPS.get(arg, ("", "CleanListen.pyw"))[1]
    if not (HERE / app).exists():
        app = "CleanListen.pyw"
    sys.argv = [str(HERE / app)]
    runpy.run_path(str(HERE / app), run_name="__main__")


def clicked(arg=""):
    """The part started from the Start menu: if the program is already open (or opening), bring
    it forward and stop; otherwise start it and show "Opening ..." until its window is up.
    False: it couldn't be started apart, so run it here as before."""
    if not _restarting() and (exists(one_name(arg)) or not hold(opening_name(arg))):
        bring_forward(arg)
        return True
    try:
        opening_note(arg).unlink(missing_ok=True)
    except OSError:
        pass
    child = start_app(arg)
    if child is None:
        return False
    try:
        splash(child, arg)
    except Exception:          # no box for it: the program opens all the same
        pass
    return True


def main():
    """As before 1.17.21: check for an update, then open the program here. Now only for "view"
    (the hand-over to the real CleanView, which has its own one-at-a-time)."""
    note = None
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if as_own_exe(arg):
            sys.exit(0)
    except Exception:      # never block the app over its name
        pass
    name = APPS.get(arg, ("CleanListen",))[0]
    try:
        # CLEANLISTEN_UPDATE_DONE: started again right after an update (start_again, or
        # CleanListen's "Check for updates")
        new = None if os.environ.pop("CLEANLISTEN_UPDATE_DONE", None) else update()
        if new:
            note = f"{name} was updated to version {new}."
            if start_again(note):
                sys.exit(0)
    except Exception as ex:  # never block the app over an update problem
        try:
            (HERE / "update_error.txt").write_text(str(ex), encoding="utf8")
        except Exception:
            pass
    if note:
        os.environ["CLEANLISTEN_UPDATED"] = note
    app = APPS.get(arg, ("", "CleanListen.pyw"))[1]
    if not (HERE / app).exists():
        app = "CleanListen.pyw"
    sys.argv = [str(HERE / app)]
    runpy.run_path(str(HERE / app), run_name="__main__")


if __name__ == "__main__":
    _arg = next((a for a in sys.argv[1:] if a != APP_PART), "")
    if _arg not in OWN:
        main()                              # "view"
    elif APP_PART in sys.argv:
        run_app(_arg)
    elif not clicked(_arg):
        run_app(_arg)
