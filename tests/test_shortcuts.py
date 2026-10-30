"""The old CleanView icon CleanListen made now leads to the real CleanView (its own program)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

import shortcuts

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def cleanview(tmp_path, monkeypatch):
    """A real CleanView install (its pythonw.exe and launcher.pyw) in a test folder."""
    root = tmp_path / "CleanView"
    monkeypatch.setattr(shortcuts, "CLEANVIEW", root)
    return root


def install(root):
    for f in (root / "venv" / "Scripts" / "pythonw.exe", root / "app" / "launcher.pyw"):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
    return root / "venv" / "Scripts" / "pythonw.exe", root / "app" / "launcher.pyw"


def test_opens_the_real_cleanview_when_it_is_installed(cleanview, monkeypatch):
    started = []
    monkeypatch.setattr(shortcuts.subprocess, "Popen", lambda cmd, **k: started.append((cmd, k["cwd"])))
    assert shortcuts.open_cleanview() is False and started == []
    pyw, launcher = install(cleanview)
    assert shortcuts.open_cleanview() is True
    assert started == [([str(pyw), str(launcher)], str(launcher.parent))]


def test_the_old_cleanview_window_is_only_a_hand_over():
    text = (REPO / "CleanView.pyw").read_text("utf8")
    assert "shortcuts.open_cleanview()" in text and "import cleanview" not in text


def test_the_old_cleanview_files_no_longer_ship():
    files = json.loads((REPO / "version.json").read_text())["files"]
    assert "cleanview.py" not in files and "cleanview.ico" not in files
    assert "CleanView.pyw" in files       # the hand-over replaces the old copy on installed PCs
    assert "cleanview_ai.py" in files     # CleanListen and CleanRead use it
    assert all((REPO / f).exists() for f in files)


def test_cleanlisten_no_longer_makes_a_cleanview_icon():
    assert not hasattr(shortcuts, "ensure_cleanview_shortcut")
    assert "ensure_cleanview_shortcut" not in (REPO / "CleanListen.pyw").read_text("utf8")


def _lnk(path, target, args):
    ps = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({shortcuts._q(path)}); "
          f"$l.TargetPath = {shortcuts._q(target)}; $l.Arguments = {shortcuts._q(args)}; $l.Save()")
    assert shortcuts._powershell(ps).returncode == 0


def _read(path):
    ps = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut({shortcuts._q(path)}); "
          "$l.TargetPath; $l.Arguments")
    return shortcuts._powershell(ps).stdout.strip().splitlines()


@pytest.mark.skipif(os.name != "nt", reason="Windows shortcuts")
def test_an_old_cleanview_icon_is_pointed_at_the_real_cleanview(cleanview, tmp_path):
    old, other = tmp_path / "desk", tmp_path / "menu"
    old.mkdir(), other.mkdir()
    _lnk(old / "CleanView.lnk", "C:\\py\\pythonw.exe", f'"{shortcuts.HERE / "launcher.pyw"}" view')
    _lnk(other / "CleanView.lnk", "C:\\elsewhere\\pythonw.exe", '"C:\\elsewhere\\launcher.pyw"')
    assert shortcuts.fix_cleanview_shortcut([old, other]) is False    # not installed: left alone
    assert _read(old / "CleanView.lnk")[0] == "C:\\py\\pythonw.exe"
    pyw, launcher = install(cleanview)
    assert shortcuts.fix_cleanview_shortcut([old, other]) is True
    assert _read(old / "CleanView.lnk") == [str(pyw), f'"{launcher}"']
    # an icon that isn't CleanListen's (e.g. the real installer's) isn't touched
    assert _read(other / "CleanView.lnk") == ["C:\\elsewhere\\pythonw.exe", '"C:\\elsewhere\\launcher.pyw"']
