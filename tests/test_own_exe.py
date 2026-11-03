"""CleanListen's and CleanRead's own names in Task Manager (Jason, 2026-11-03: they showed as
"Python"). launcher.pyw makes CleanListen.exe / CleanRead.exe, copies of pythonw.exe with the
app's description and icon, and only uses one once a test run of it worked."""
import ctypes
import importlib.machinery
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def lm():
    loader = importlib.machinery.SourceFileLoader("cl_launcher_test", str(ROOT / "launcher.pyw"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def description(path):
    v = ctypes.windll.version
    n = v.GetFileVersionInfoSizeW(str(path), None)
    buf = ctypes.create_string_buffer(n)
    v.GetFileVersionInfoW(str(path), 0, n, buf)
    p, size = ctypes.c_wchar_p(), ctypes.c_uint()
    v.VerQueryValueW(buf, r"\StringFileInfo\040904B0\FileDescription", ctypes.byref(p), ctypes.byref(size))
    return p.value


needs_venv = pytest.mark.skipif(not (os.name == "nt" and sys.prefix != sys.base_prefix
                                     and (Path(sys.prefix) / "pyvenv.cfg").exists()),
                                reason="needs Windows and the app's venv")


@pytest.fixture
def venv(tmp_path):
    v = tmp_path / "venv"
    v.mkdir()
    shutil.copy2(Path(sys.prefix) / "pyvenv.cfg", v / "pyvenv.cfg")
    return v


@needs_venv
@pytest.mark.parametrize("name,icon", [("CleanListen", "icon.ico"), ("CleanRead", "cleanread.ico")])
def test_named_with_its_icon_and_made_once(lm, venv, name, icon):
    exe = lm.make_own_exe(name, ROOT / icon, venv / name, sys.base_prefix)
    assert exe == venv / name / f"{name}.exe"
    assert description(exe) == name
    assert ctypes.windll.shell32.ExtractIconExW(str(exe), -1, None, None, 0) == 1
    when = exe.stat().st_mtime_ns
    assert lm.make_own_exe(name, ROOT / icon, venv / name, sys.base_prefix) == exe
    assert exe.stat().st_mtime_ns == when


@needs_venv
def test_a_failed_try_isnt_used_or_tried_again(lm, venv):
    with mock.patch.object(lm, "_rename_exe", side_effect=OSError("no")):
        assert lm.make_own_exe("CleanRead", ROOT / "cleanread.ico", venv / "CleanRead", sys.base_prefix) is None
    assert "no" in (venv / "CleanRead" / "failed.txt").read_text(encoding="utf8")
    with mock.patch.object(lm, "_rename_exe") as again:
        assert lm.make_own_exe("CleanRead", ROOT / "cleanread.ico", venv / "CleanRead", sys.base_prefix) is None
        again.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_not_while_smart_app_control_is_on(lm):
    with mock.patch.object(lm, "_smart_app_control_off", return_value=False), \
            mock.patch.object(lm, "make_own_exe") as make, \
            mock.patch.object(lm.sys, "executable", r"C:\venv\Scripts\pythonw.exe"):
        assert not lm.as_own_exe("read")
        make.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_each_app_its_own_exe_and_never_for_cleanview(lm):
    with mock.patch.object(lm, "_smart_app_control_off", return_value=True), \
            mock.patch.object(lm, "make_own_exe", return_value=None) as make:
        with mock.patch.object(lm.sys, "executable", r"C:\venv\CleanRead\CleanRead.exe"):
            assert not lm.as_own_exe("read")
            make.assert_not_called()
            assert not lm.as_own_exe("")              # CleanListen started from CleanRead.exe
            assert make.call_args[0][0] == "CleanListen"
        make.reset_mock()
        assert not lm.as_own_exe("view")              # the hand-over to the real CleanView
        make.assert_not_called()


def test_the_cleanread_shortcut_uses_the_venvs_pythonw(tmp_path):
    import shortcuts
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "pythonw.exe").write_bytes(b"")
    with mock.patch.object(shortcuts.sys, "prefix", str(tmp_path)), \
            mock.patch.object(shortcuts.sys, "executable", str(tmp_path / "CleanListen" / "CleanListen.exe")):
        assert shortcuts._pythonw() == scripts / "pythonw.exe"


# The first start after an update showed "Python" (Jason, 2026-11-03): the old launcher
# downloaded the new one but opened the app itself. Now it starts the new launcher.
def _main(lm, argv, env=None, new=None):
    calls = {}
    with mock.patch.object(lm, "as_own_exe", return_value=False), \
            mock.patch.object(lm, "update", return_value=new) as upd, \
            mock.patch.object(lm, "start_again", side_effect=lambda note: calls.setdefault("again", note)) as again, \
            mock.patch.object(lm.runpy, "run_path", side_effect=lambda p, **k: calls.setdefault("ran", p)), \
            mock.patch.object(lm.sys, "argv", argv), mock.patch.dict(lm.os.environ, env or {}):
        try:
            lm.main()
        except SystemExit:
            calls["exit"] = True
        calls["checked"] = upd.called
        calls["update_done_left"] = "CLEANLISTEN_UPDATE_DONE" in lm.os.environ
    return calls


def test_after_an_update_the_new_launcher_opens_the_app(lm):
    c = _main(lm, ["launcher.pyw", "read"], new="1.13.2")
    assert c["again"] == "CleanRead was updated to version 1.13.2." and c["exit"] and "ran" not in c


def test_the_new_launcher_doesnt_check_again(lm):
    c = _main(lm, ["launcher.pyw", "read"], env={"CLEANLISTEN_UPDATE_DONE": "1"}, new="9.9")
    assert not c["checked"] and "again" not in c and c["ran"].endswith("CleanRead.pyw")
    assert not c["update_done_left"]          # not passed on to anything the app starts


def test_no_update_opens_the_app_as_before(lm):
    c = _main(lm, ["launcher.pyw"], new=None)
    assert c["checked"] and "again" not in c and c["ran"].endswith("CleanListen.pyw")


def test_start_again_runs_the_new_launcher_with_the_note(lm):
    with mock.patch("subprocess.Popen") as popen, mock.patch.object(lm.sys, "argv", ["launcher.pyw", "read"]):
        assert lm.start_again("CleanRead was updated to version 1.13.2.")
    args, kw = popen.call_args
    assert args[0][1:] == [str(ROOT / "launcher.pyw"), "read"]
    assert kw["env"]["CLEANLISTEN_UPDATE_DONE"] == "1"
    assert kw["env"]["CLEANLISTEN_UPDATED"] == "CleanRead was updated to version 1.13.2."


def test_cleanlistens_update_button_restarts_through_the_launcher():
    src = (ROOT / "CleanListen.pyw").read_text(encoding="utf8")
    assert 'subprocess.Popen([sys.executable, str(HERE / "launcher.pyw")]' in src
    assert 'CLEANLISTEN_UPDATE_DONE="1"' in src
