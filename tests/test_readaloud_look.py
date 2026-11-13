"""ReadAloud in CleanView's new look (the owner, 2026-11-13: "change read aloud to the style of the
new cleanview. i know that tick boxes are diffent but bring the styling over"): the start page one
step at a time, rounded cards and buttons, and light or dark, kept with CleanListen's choice."""
import importlib.util
import os
import re
import time

import pytest

from conftest import REPO

os.environ["READALOUD_FAKE_VOICE"] = "1"


def test_no_colour_is_written_into_a_page():
    # every colour is a name from cllook.py with a value for light and for dark
    src = (REPO / "ReadAloud.pyw").read_text("utf8")
    assert re.findall(r'"#[0-9A-Fa-f]{6}"', src) == []
    assert "CL.StepPage(" in src and "CL.style(self, s)" in src


@pytest.fixture
def window(tmp_path, monkeypatch):
    import filters as F
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    spec = importlib.util.spec_from_file_location("ReadAloudLook", REPO / "ReadAloud.pyw")
    win = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(win)
    monkeypatch.setattr(win, "SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(win, "APP_DATA", tmp_path)
    monkeypatch.setattr(win.engine, "JOBS", tmp_path / "jobs")
    w = win.freezes.Watch
    monkeypatch.setattr(win.freezes, "Watch", lambda root, app, folder, prefix="": w(root, app, tmp_path, prefix))
    app = win.App()
    yield win, app
    app.destroy()
    win.use_theme("light")


def _pump(app, sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        app.update()


def test_the_start_page_is_five_steps_and_says_whats_chosen(window, tmp_path):
    win, app = window
    from test_readaloud import STORY, make_epub
    sp = app.steps_page
    assert [t for t, _ in sp.steps] == ["Ebook", "Voice", "Reading director", "What to read", "Save to"]
    assert app.start_btn.cget("text") == "Make audiobook" and app.start_btn.cget("state") == "disabled"
    b = win.engine.load_book(make_epub(tmp_path / "book.epub", STORY))
    app.q.put(("book", str(tmp_path / "book.epub"), b, None))
    _pump(app, 0.5)
    assert app.start_btn.cget("state") == "normal"
    said = [row[3].cget("text") for row in sp.rows]
    assert said[0] == "Nearly Safe" and said[3] == "2 of 3 parts" and said[4] == "Next to the ebook"
    app.director_var.set(False)
    app._director_changed()
    assert not app.director_more.winfo_ismapped() and sp.rows[2][3].cget("text") == "Off"


def test_dark_keeps_the_book_the_ticks_and_the_step(window, tmp_path):
    win, app = window
    import filters as F
    from test_readaloud import STORY, make_epub
    b = win.engine.load_book(make_epub(tmp_path / "book.epub", STORY))
    app.q.put(("book", str(tmp_path / "book.epub"), b, None))
    _pump(app, 0.5)
    app.steps_page.go(4)
    app.chapter_vars[1].set(False)
    app.series_var.set("My series")
    light_bg = app.cget("bg")
    app.theme_var.set("dark")
    app._set_theme()
    _pump(app)
    assert win.THEME == "dark" and app.cget("bg") != light_bg and F.load()["theme"] == "dark"
    assert app.steps_page.now == 4 and app.book is b
    assert [v.get() for v in app.chapter_vars] == [False, False, True]
    assert app.series_var.get() == "My series"


def test_the_next_window_opens_in_the_look_chosen(tmp_path, monkeypatch):
    import filters as F
    monkeypatch.setattr(F, "SAVED", tmp_path / "filters.json")
    F.save({"theme": "dark"})
    spec = importlib.util.spec_from_file_location("ReadAloudLook2", REPO / "ReadAloud.pyw")
    win = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(win)
    monkeypatch.setattr(win, "APP_DATA", tmp_path)
    monkeypatch.setattr(win.engine, "JOBS", tmp_path / "jobs")
    w = win.freezes.Watch
    monkeypatch.setattr(win.freezes, "Watch", lambda root, app, folder, prefix="": w(root, app, tmp_path, prefix))
    app = win.App()
    try:
        assert win.THEME == "dark" and app.theme_var.get() == "dark"
    finally:
        app.destroy()
        win.use_theme("light")


def test_the_updated_line_goes_and_the_lists_are_round(window, monkeypatch):
    # as CleanView 1.18.84-1.18.85 (the owner, 2026-11-13, asked about bringing them to ReadAloud: "both")
    win, app = window
    monkeypatch.setattr(win.CL, "UPDATED_SHOWN_SECS", 0.3)
    monkeypatch.setenv("CLEANLISTEN_UPDATED", "ReadAloud was updated to version 9.9.9")
    app.show_setup()
    said = [w for w in app.steps_page.top.winfo_children() if isinstance(w, win.tk.Label)
            and "updated" in str(w.cget("text"))]
    assert said
    _pump(app, 0.6)
    assert not said[0].winfo_exists()
    assert app.voice_box.cget("style") == app.speed_box.cget("style") == "Round.TCombobox"
