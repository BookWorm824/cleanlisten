"""CleanListen launcher: checks GitHub for a newer version, updates the
program files if there is one, then opens the app (CleanListen, or CleanRead
when started with "read"; "view" opens CleanView.pyw, which hands over to the real CleanView,
its own program now). If the check fails (offline, GitHub down) the app
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


# ---------- each app's own name in Task Manager ----------
# Task Manager names a program by its .exe's description, so CleanListen and CleanRead showed
# as "Python" (Jason, 2026-11-03). As in CleanView 1.18.9: CleanListen.exe / CleanRead.exe are
# copies of the venv's base pythonw.exe in venv\CleanListen and venv\CleanRead, with
# python312.dll beside them and their description and icon changed; each finds the venv
# through venv\pyvenv.cfg one folder up, like Scripts\pythonw.exe does. (Not in Scripts:
# sherpa-onnx put an onnxruntime.dll there, which an .exe in that folder would load first.)
# The changed .exe has no signature, so Smart App Control would block it: it's only made while
# that's off, and only used once a test run of it has worked (never tried again once it failed).
OWN = {"": ("CleanListen", "icon.ico"), "read": ("CleanRead", "cleanread.ico")}
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
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if as_own_exe(arg):
            sys.exit(0)
    except Exception:      # never block the app over its name
        pass
    name = {"view": "CleanView", "read": "CleanRead"}.get(arg, "CleanListen")
    try:
        new = update()
        if new:
            note = f"{name} was updated to version {new}."
    except Exception as ex:  # never block the app over an update problem
        try:
            (HERE / "update_error.txt").write_text(str(ex), encoding="utf8")
        except Exception:
            pass
    if note:
        os.environ["CLEANLISTEN_UPDATED"] = note
    app = {"view": "CleanView.pyw", "read": "CleanRead.pyw"}.get(arg, "CleanListen.pyw")
    if not (HERE / app).exists():
        app = "CleanListen.pyw"
    sys.argv = [str(HERE / app)]
    runpy.run_path(str(HERE / app), run_name="__main__")
