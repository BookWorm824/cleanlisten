"""A fresh install opens: everything the launcher needs before its window is downloaded by setup
(2026-11-04: 1.14.1's setup took only version.json's list, update.json wasn't on it, and
CleanListen stopped before its window opened)."""
import importlib.util
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_update_json_is_on_the_list_setup_downloads():
    assert "update.json" in json.loads((REPO / "version.json").read_text())["files"]
    assert json.loads((REPO / "update.json").read_text())["repo"] == "BookWorm824/cleanlisten"


def _load_launcher(folder):
    spec = importlib.util.spec_from_loader("launcher_t", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(folder / "launcher.pyw")
    exec(compile((folder / "launcher.pyw").read_text("utf8"), mod.__file__, "exec"), mod.__dict__)
    return mod


def test_the_launcher_starts_without_update_json(tmp_path):
    shutil.copy2(REPO / "launcher.pyw", tmp_path / "launcher.pyw")
    mod = _load_launcher(tmp_path)              # stopped here with FileNotFoundError before
    assert mod.RAW == "https://raw.githubusercontent.com/BookWorm824/cleanlisten/main/"
    (tmp_path / "update.json").write_text("not json")
    assert _load_launcher(tmp_path).CONFIG["repo"] == "BookWorm824/cleanlisten"


def test_setup_writes_update_json_if_its_missing():
    ps = (REPO / "installer" / "install.ps1").read_text("utf8")
    assert "update.json" in ps and '"repo": "BookWorm824/cleanlisten"' in ps
