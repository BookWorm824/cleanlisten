"""The slight 3D logos (the owner, 2026-11-15, in CleanView: she picked look "E · All of it", then
"apply to each chat"), and the desktop, Start menu and taskbar shortcuts brought up to date: Windows
keeps a picture of a shortcut's icon by the icon file's name, so they'd keep the old logo."""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

import logo
import shortcuts

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import icon_3d  # noqa: E402


def picture(ico):
    png, _ = logo.logo_png(ico, 256)
    return logo._png_rgba(png)


@pytest.mark.parametrize("ico,flat", [("icon.ico", "icon_flat.ico"), ("cleanread.ico", "cleanread_flat.ico")])
def test_the_logos_have_the_3d_look_made_from_the_flat_ones(ico, flat, tmp_path):
    out = tmp_path / ico
    icon_3d.write_ico(out, icon_3d.three_d(icon_3d.png_rgba(icon_3d.read_ico(REPO / "tools" / flat)[256])))
    assert out.read_bytes() == (REPO / ico).read_bytes()       # made again, it comes out the same
    new, old = picture(ico).astype(int), picture("tools/" + flat).astype(int)
    assert (new[..., 3] == old[..., 3]).all()                   # the same shape
    top, bottom = new[30, 128, :3].sum(), new[226, 128, :3].sum()
    assert top > bottom + 60                                    # light from above
    assert sorted(icon_3d.read_ico(REPO / ico)) == [16, 24, 32, 48, 64, 128, 256]


@pytest.mark.parametrize("flat,big", [("icon_flat.ico", "cleanlisten_logo.png"),
                                      ("cleanread_flat.ico", "cleanread_logo.png")])
def test_the_512_logos_for_the_working_page(flat, big):
    # at the strength she picked ("4 is goood": 2.2 times look E), edges kept sharp
    assert icon_3d.MORE == 2.2
    pic = icon_3d.three_d(icon_3d.enlarge(icon_3d.png_rgba(icon_3d.read_ico(REPO / "tools" / flat)[256])))
    assert icon_3d.png(pic) == (REPO / big).read_bytes()
    a = logo._png_rgba((REPO / big).read_bytes())
    assert a.shape == (512, 512, 4) and a[0, 0, 3] == 0 and a[256, 256, 3] == 255
    soft = ((a[..., 3] > 10) & (a[..., 3] < 245)).sum()
    assert soft < 512 * 4 * 3                       # a thin soft edge, not a blurry one


def test_the_working_page_uses_the_512_logo_and_fits_the_room():
    for ico in ("icon.ico", "cleanread.ico"):
        assert logo.logo_rgba(ico, logo.WORKING_LOGO).shape == (512, 512, 4)
        assert logo.logo_rgba(ico, 256) is None or ico == "cleanread.ico"
    assert logo.fit_size(384, 900, 600) == 384
    assert logo.fit_size(384, 900, 300) == 272      # smaller, not cut off
    assert logo.fit_size(384, 60, 60) == 48
    import json
    files = json.loads((REPO / "version.json").read_text())["files"]
    assert "cleanlisten_logo.png" in files and "cleanread_logo.png" in files


def test_the_flat_logos_and_the_tool_are_kept_but_not_shipped():
    import json
    files = json.loads((REPO / "version.json").read_text())["files"]
    for f in ("tools/icon_3d.py", "tools/icon_flat.ico", "tools/cleanread_flat.ico"):
        assert (REPO / f).exists() and f not in files
    assert "icon.ico" in files and "cleanread.ico" in files


def _lnk(path, args, icon=""):
    ps = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({shortcuts._q(path)}); "
          f"$l.TargetPath = {shortcuts._q(sys.executable)}; $l.Arguments = {shortcuts._q(args)}; "
          + (f"$l.IconLocation = {shortcuts._q(icon)}; " if icon else "") + "$l.Save()")
    assert shortcuts._powershell(ps).returncode == 0


def _icon_of(path):
    ps = f"(New-Object -ComObject WScript.Shell).CreateShortcut({shortcuts._q(path)}).IconLocation"
    return shortcuts._powershell(ps).stdout.strip()


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")
def test_the_shortcuts_get_the_new_logo_once(tmp_path, monkeypatch):
    app, desk, data = tmp_path / "app", tmp_path / "desk", tmp_path / "data"
    app.mkdir()
    desk.mkdir()
    monkeypatch.setattr(shortcuts, "APP_DATA", data)
    (app / "launcher.pyw").write_text("")
    (app / "icon.ico").write_bytes((REPO / "icon.ico").read_bytes())
    (app / "cleanread.ico").write_bytes((REPO / "cleanread.ico").read_bytes())
    launcher = app / "launcher.pyw"
    _lnk(desk / "CleanListen.lnk", f'"{launcher}"', str(app / "icon.ico"))
    _lnk(desk / "CleanRead.lnk", f'"{launcher}" read', str(app / "cleanread.ico"))
    _lnk(desk / "ReadAloud.lnk", '"C:\\somewhere else\\launcher.pyw" aloud')   # another install's
    assert shortcuts.new_icons_on_shortcuts(here=app, places=[desk]) == ["CleanListen", "CleanRead"]
    mark = shortcuts.icon_mark(app / "icon.ico")
    assert _icon_of(desk / "CleanListen.lnk") == f"{app / ('icon-' + mark + '.ico')},0"
    assert (app / f"icon-{mark}.ico").read_bytes() == (app / "icon.ico").read_bytes()
    assert _icon_of(desk / "CleanRead.lnk").startswith(str(app / "cleanread-"))
    assert "somewhere" not in _icon_of(desk / "ReadAloud.lnk") and not list(app.glob("readaloud-*"))
    assert shortcuts.shown_icon("icon.ico", app) == app / f"icon-{mark}.ico"
    # once: the next start leaves them alone
    assert shortcuts.new_icons_on_shortcuts(here=app, places=[desk]) == []
    # another new logo: a new copy, the old one gone
    (app / "icon.ico").write_bytes((REPO / "tools" / "icon_flat.ico").read_bytes())
    assert shortcuts.new_icons_on_shortcuts(here=app, places=[desk]) == ["CleanListen"]
    mark2 = shortcuts.icon_mark(app / "icon.ico")
    assert _icon_of(desk / "CleanListen.lnk") == f"{app / ('icon-' + mark2 + '.ico')},0"
    assert sorted(p.name for p in app.glob("icon-*.ico")) == [f"icon-{mark2}.ico"]


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")
def test_no_shortcut_no_copy_left_behind(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "icon.ico").write_bytes((REPO / "icon.ico").read_bytes())
    monkeypatch.setattr(shortcuts, "APP_DATA", tmp_path / "data")
    assert shortcuts.new_icons_on_shortcuts(here=app, places=[tmp_path / "empty"]) == []
    assert not list(app.glob("icon-*.ico"))
    assert shortcuts.shown_icon("icon.ico", app) == app / "icon.ico"


def test_only_the_installed_copy_changes_real_shortcuts(monkeypatch):
    monkeypatch.setattr(shortcuts, "installed_copy", lambda: False)
    monkeypatch.setattr(shortcuts, "_new_icon_on_shortcuts", lambda *a: pytest.fail("touched shortcuts"))
    assert shortcuts.new_icons_on_shortcuts() == []


@pytest.fixture
def lm():
    loader = importlib.machinery.SourceFileLoader("cl_launcher_3d", str(REPO / "launcher.pyw"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def test_an_exe_made_before_gets_the_new_icon_once(lm, tmp_path, monkeypatch):
    exe, icon = tmp_path / "CleanListen.exe", tmp_path / "icon.ico"
    exe.write_bytes(b"old exe")
    icon.write_bytes(b"new logo")
    calls = []

    def stamp(path, name, ico):
        calls.append(name)
        Path(path).write_bytes(b"exe with " + Path(ico).read_bytes())
    monkeypatch.setattr(lm, "_rename_exe", stamp)
    lm._new_icon_on_exe(exe, "CleanListen", icon)
    assert exe.read_bytes() == b"exe with new logo" and calls == ["CleanListen"]
    assert (tmp_path / "icon.txt").read_text() == lm._icon_mark(icon)
    lm._new_icon_on_exe(exe, "CleanListen", icon)
    assert calls == ["CleanListen"]                      # once
    assert not (tmp_path / "CleanListen.exe.new").exists()


def test_an_exe_in_use_is_left_for_next_time(lm, tmp_path, monkeypatch):
    exe, icon = tmp_path / "CleanRead.exe", tmp_path / "cleanread.ico"
    exe.write_bytes(b"old exe")
    icon.write_bytes(b"new logo")
    monkeypatch.setattr(lm, "_rename_exe", lambda *a: None)
    monkeypatch.setattr(lm.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError("in use")))
    lm._new_icon_on_exe(exe, "CleanRead", icon)
    assert exe.read_bytes() == b"old exe" and not (tmp_path / "icon.txt").exists()
    assert not (tmp_path / "CleanRead.exe.new").exists()


def test_the_launcher_starts_the_shortcut_update():
    text = (REPO / "launcher.pyw").read_text(encoding="utf8")
    assert "threading.Thread(target=_new_icons_on_shortcuts, daemon=True).start()" in text
    assert "_new_icon_on_exe(exe, name, icon)" in text
