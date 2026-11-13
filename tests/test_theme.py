"""Light and dark (as CleanView 1.18.78; the owner, 2026-11-13: "ask cleann view aabout dark mode
built. lets move that here also"; there: "yes it should be optional", "just light dark button option.
no windows choice"). Every colour the windows use is a name in cllook.py with a value for each look;
light is the look as it was and the default; the choice is kept in filters.json, which CleanListen
and CleanRead share."""
import importlib.machinery
import importlib.util
import re
import types

import pytest

import cllook as CL
import cvlook as look
import filters as F
from conftest import REPO


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / file))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def back_to_light():
    yield
    CL.use_theme("light")


def test_every_colour_has_a_value_for_each_look():
    assert set(CL.LIGHT) == set(CL.DARK)
    assert set(CL.LIGHT["PIECES"]) == set(CL.DARK["PIECES"])
    for pal in (CL.LIGHT, CL.DARK):
        for k, v in pal.items():
            vals = v.values() if isinstance(v, dict) else v if isinstance(v, tuple) else [v]
            assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in vals), k


def test_light_is_the_look_as_it_was():
    L = CL.LIGHT
    assert (L["BG"], L["CARD"], L["INK"], L["MUTED"], L["ACCENT"], L["ACCENT_DK"], L["LINE"]) == (
        "#F6F3EE", "#FFFFFF", "#23211F", "#5C5852", "#2F6F62", "#24574D", "#E3DED6")
    assert CL.THEME == "light" and look.C["bg"] == "#F6F3EE"


@pytest.mark.parametrize("app", ["CleanListen.pyw", "CleanRead.pyw"])
def test_no_colour_is_written_into_a_page(app):
    src = (REPO / app).read_text(encoding="utf8")
    assert re.findall(r'"#[0-9A-Fa-f]{6}"', src) == []          # name it in cllook.py
    assert not re.search(r"def \w+\([^)]*=(BG|CARD|INK|MUTED|ACCENT|LINE)\b", src)   # read when used


@pytest.mark.parametrize("app", ["CleanListen.pyw", "CleanRead.pyw"])
def test_use_theme_sets_the_apps_names(app):
    m = load("theme_" + app[:9].lower(), app)
    assert m.THEME == "light" and m.BG == CL.LIGHT["BG"] and m.GO == m.ACCENT
    m.use_theme("dark")
    assert m.THEME == "dark" and m.BG == CL.DARK["BG"] and m.CARD == CL.DARK["CARD"]
    assert m.GO == m.ACCENT == CL.DARK["ACCENT"] and m.GO_OFF == CL.DARK["DISABLED"]
    assert look.C["bg"] == CL.DARK["BG"] and look.C["tick_off"] == CL.DARK["PIECES"]["tick_off"]
    m.use_theme("anything else")
    assert m.THEME == "light" and m.INK == CL.LIGHT["INK"]


@pytest.mark.parametrize("app", ["CleanListen.pyw", "CleanRead.pyw"])
def test_the_choice_is_kept_and_the_page_built_again(app, tmp_path, monkeypatch):
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    monkeypatch.setattr(F, "APP_DATA", tmp_path)
    m = load("theme2_" + app[:9].lower(), app)
    monkeypatch.setattr(m.CL, "title_bar", lambda root: None)
    done = []
    me = types.SimpleNamespace(
        theme_var=types.SimpleNamespace(get=lambda: "dark"), steps_page=types.SimpleNamespace(now=3),
        _keep_for_rebuild=lambda: done.append("kept"), configure=lambda **k: done.append(k["bg"]),
        _style=lambda: done.append("style"), show_setup=lambda step=1: done.append(("page", step)))
    m.App._set_theme(me)
    assert done == ["kept", CL.DARK["BG"], "style", ("page", 3)]
    assert F.load()["theme"] == "dark" and m.THEME == "dark"
    done.clear()
    m.App._set_theme(me)                         # already dark: nothing to do
    assert done == []
    m.App._set_theme(me, "light")
    assert F.load()["theme"] == "light" and m.THEME == "light"


def test_the_filter_tiles_use_the_look_in_use():
    src = (REPO / "filters.py").read_text(encoding="utf8")
    body = src[src.index("def build_boxes("):src.index("def read_boxes(")]
    assert 'CARD, INK, MUTED, LINE, ACCENT = C["card"]' in body
    assert re.findall(r'"#[0-9A-Fa-f]{6}"', body) == []
